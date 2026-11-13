# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## 0.4.0 — 2026-11-12 — Templates, modules and local services

### Upgrade

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead. This update
   is still the old engine's: it installs into `<BRAIN_HOME>/venv` as before (see the blue-green note below).
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered. Until then a session's
   hooks are the older engine's: they append to the ledgers (`ar`, `ddr`, `events`, the guards, queue, answers and
   cockpit ledgers, the quota readings, the session starts, the notify audit and its held messages) without the
   folder's lock, so sessions writing at once on Windows can still lose or mix lines.
3. **Refresh the public stamp**: a stamp is valid only under the engine that made it, so the push guard refuses the
   old one. From 0.4.0 on, `brain update` and the installer's `-Apply` refresh them (`brain check --public --refresh`:
   each local checkout of `public.repos` in the registry); this once, the `brain update` that installs 0.4.0 is
   0.3.2's and does not, so run `brain check --public --refresh` in your own terminal after step 1 (the installer's
   `-Apply` from this tag runs it, its `stamps` step). A checkout it skipped (uncommitted work, named in its output)
   or one outside the registry gets `brain check --public --history` by hand before its next push; a checkout with
   findings is named and not stamped, and another local branch still asks its own check.
4. **Declare the new engine stores**, in a brain whose `config.json` declares `classes`: `brain classes --suggest`
   prints the lines it misses for `classes.stores`, to add by a PR: `machine.json` (this machine's identity),
   `facts.json` (its last facts), `locks` (the single-instance locks), `ipc` (the machine's token for the local
   services, secret), `views` (the renderings as of a point, `brain reference --asof`), `merge-ready` (the merge
   gate's stamps), `formats` (the projects' format checks) and `venvs` (`brain update`'s slots). Until then each takes
   its suggested class (secret for `ipc`, sealed for the others) and `brain classes --check` names them as undeclared,
   without failing. A brain with no `classes` block has nothing to do.
5. **Add the documentation graph's lines** to a brain made before 0.4.0 whose store has the `Doc` type, as
   `brain init` now writes them: `notes/docs_graph.md merge=brain` in `.gitattributes`, and
   `- {glob: "notes/docs_graph.md", side: generated, why: "brain sync (brain.docsgraph: the documentation graph)"}`
   among the generated rules of `boundary.yaml`. `brain sync` now writes that view; until the lines are there it
   merges as plain text and the boundary does not know it as generated.
6. **Check this machine's profile and facts**: `brain doctor`, then `brain mod explain ID` for a module you rely on.
   A machine's `profile.json` is now merged key by key over `config.json` `tier.components` (a switch it does not name
   keeps the brain's default), and module ids are accepted in both, expanded to their capabilities. Each fact is now
   true, false or unknown: an unknown fact (never probed, or a probe that could not say) satisfies neither `FACT` nor
   `not FACT` in a `recommend_when`, nor `FACT != VALUE`, so a recommendation, or a `not FACT` or `!=` clause, that
   held on a fact nobody knew no longer does (a requirement on an unknown fact already counted as missing in 0.3.2);
   declare the fact in `config.json` `hosts.<name>` (ecc, battery, encrypted, gpu, type, cluster, roles) where the
   probe cannot say. The first run writes `<BRAIN_HOME>/machine.json` (the name, `$BRAIN_MACHINE` else the host name,
   and a sha256 anchor of the OS install); `brain doctor` prints the `hosts` line to add to `config.json` (optional,
   what tells a reused name or a cloned image). A doubt on the identity holds the memory export, imports going on,
   while it lasts; `brain doctor` names it, and no command answers it: a renamed machine clears when `$BRAIN_MACHINE`
   gives back its first name, or once `<BRAIN_HOME>/machine.json` is removed (the next run takes the name as a first
   sight); a copied `BRAIN_HOME` or cloned image once that machine has its own `BRAIN_HOME` and name (or its
   `machine.json` removed); a name reused, or an anchor given to two names, once `config.json` `hosts` is corrected.
   An install id that cannot be read (a Linux system or container with neither `/etc/machine-id` nor
   `/var/lib/dbus/machine-id`, a Python whose platform is not Windows, Linux or macOS, such as an MSYS build) is a
   doubt that nothing clears in this release, a `hosts` line included, whatever the doubt's text says: that machine
   exports no memory until it has an install id (`systemd-machine-id-setup` or `dbus-uuidgen --ensure`) or runs the
   brain from a Windows, Linux or macOS Python. Under the new optional
   `config.json` `engine.min` (no floor when absent), an older engine writes no DDR and exports no memory, and
   `brain check` says so.

What this release newly refuses, skips or reads differently, with nothing to run:

- **One cockpit and one alerts pass per machine** (a lock under `<BRAIN_HOME>/locks/`): a second interactive
  `brain tui` is refused, and a second `brain alerts --notify` pass (a scheduled one overlapping another) is skipped.
  A signal (SIGINT, SIGTERM, SIGHUP, Ctrl+Break) now stops a command once its ledger line or state write is whole; on
  Windows it exits 128 + the signal's number.
- **Blue-green updates**: the first `brain update` run by 0.4.0 or later (the next release's) installs the new
  version in `<BRAIN_HOME>/venvs/vX.Y.Z`, moves today's real `venv` folder into `venvs/v<its version>` and makes
  `<BRAIN_HOME>/venv` a link to the active slot (a junction on Windows, a symlink elsewhere) only once the new slot
  passes its health gate, a watchdog switching back to the previous slot when one fails; three slots are kept. The
  hooks, the installer, the shim and anything else that reads `<BRAIN_HOME>/venv` follow the link.
- **Signed tags**: `brain update` and the installer now give a tag whose ref names another release's signed tag
  object the verdict `misnamed`, refused under `engine.verify_tags` (off when absent); the installer says whether it
  runs from the commit the signed tag names, never a refusal.
- **Formats**: `docgraph/v1`, `catalogue/v1`, `reference` (`docs/reference.yaml`) and `permissions.yaml` get their
  registered schemas, all new; `docgraph/v1` and `catalogue/v1` evolve additively (an optional key within v1). The
  status document gains an optional `hardware`. `config.json`'s schema grows by optional keys only (`hosts`,
  `engine.min`, `inventory.nodes_file`, `inventory.agent_json`, `scope_types`, `ipc.require_token`, `ipc.mcp_port`,
  `public.deny_from_tree`, `audit.schema_diff_strict`). `projects.yaml` takes the optional `formats:` and
  `migrations:` (and `parent:`, `classes:`, beside the new optional `scopes.yaml`): an older engine notes them and
  keeps them (in CI: refused), so a registry declares them once every machine runs this release. research-graph's
  `schema.yaml` takes the optional `templates:` and `endpoints:`; a schema without them is read and checked as
  before.
- **Templates**: the project templates (`cli`, `data-pipeline`, `local-client`, `research`, `service` and their bases
  `_project`, `_software`) need this engine (`engine: ">=0.4.0"`, for keys such as `takes`); `generic` is unchanged.
  `brain init` now also writes an empty `modules` key and the step 5 lines.
- **Opt-in, off until the owner turns it on**: `public.deny_from_tree` (with it on, a scope tree or registry that
  cannot be read makes the public guard refuse), `ipc.require_token` (the collector's token, with Claude Code's OTLP
  headers then needed), the `infra-node` capability, `audit.schema_diff_strict`, and `brain mcp serve`, which runs
  only when launched, every tool call judged by the guards, strictly.
- **The docs set**: a frozen store (`tests/fixtures/stores/**`) is left out of the docs set and the shape signals, so
  a README under such a folder is no longer a Doc node after the next `brain sync`; nothing newly refused.

Nothing to run for the rest.

### Added

- `brain ipc otel-headers` prints the OTLP export's headers, `{"Authorization": "Bearer <token>"}`, for Claude Code's
  `otelHeadersHelper` setting: the export authenticates to a collector that requires the machine's token
  (`ipc.require_token`) without the token sitting in clear in `OTEL_EXPORTER_OTLP_HEADERS`. Without a usable token
  it prints nothing on stdout and exits 1. A session never runs it: the owner guard refuses it (`keys`) and the MCP
  server's guards refuse every `brain ipc` command (`wi-brain-local-ipc-auth`).
- Checking a decision against the target before it is accepted (`wi-brain-adr-target-check`,
  [docs/adr-target.md](docs/adr-target.md)): `brain adr new --scope S --target ID=COMPAT[:note] --leaves-open T`
  writes a one-way door's Scope and Target compatibility (each future need it touches, compatible, an extension point
  or to review, and what it leaves open; one without the other is written TODO). `brain adr target [--needs] [--json]`
  computes the register of future needs from the graph (the planned features, the pending milestones with a trigger,
  the open items of later waves and of the pending eras) and runs three advisory checks on the one-way doors (an ADR
  with either field, written by the command or by hand as a label or a sentence): `decision.target-compat-missing`,
  `decision.review-trigger-missing` and `decision.target-unreferenced` (an open need of a module the ADR decides that
  it does not cite). `brain docgraph emit` adds the register, the one-way decisions and their `constrains` edges to the
  brain's documentation graph, and `brain docgraph join` runs `decision.target-unreferenced` across the joined graph.
  Two-way doors are never checked.
- `catalogue/v1`, the module catalogue's neutral contract (`wi-brain-catalogue-contract`,
  [docs/catalogue.md](docs/catalogue.md)): a public, versioned JSON format any program may emit for a catalogue of
  modules (its bricks; its modules with their hard and soft dependencies, the machine facts they require, the clauses
  that recommend them, their estimated cost in RAM, disk, VRAM and download, their fallback and licence; the
  distributions that ship them, with a digest and a signature to install offline; and the presets an installer
  offers, base ones and the personas a private catalogue declares), so one installer and one Modules tab read every
  catalogue. Its schema is `schemas/catalogue.schema.json`, registered with the other formats, with an invented
  catalogue of each side of the version in `tests/fixtures/formats/catalogue/v1/`; it evolves by the status
  contract's rule (an unknown key tolerated at every level, a new class, status or preset kind is v2, a typology id no
  catalogue holds yet kept, never refused; `release-check` counts an optional key added to its schema as a patch, as for
  docgraph/v1). `brain catalogue validate FILE...` checks a document against it (exit 1 when invalid or written for a
  later version; no brain needed) and `brain catalogue emit [--out FILE]` prints the brain's own: `brain mod`'s
  modules, the engine and its extras as distributions, and the presets Lite, Default and Recommended.
- A plugged project's cockpit panels and tabs, declared as data (`wi-brain-command-plugins-cockpit`,
  `brain.plugin_panels`): its plugin's `COCKPIT` mapping names each panel's rows (a JSON file under the project's root,
  or a `module:attr` callable), its columns, sorts, filters and help, and its tabs. `brain tui` draws each panel as one
  of its own tables (search, sorts, filters, saved views, columns, palette, detail, `--once`), its tab after Resources
  with no number (`--tab <project>`); its rows are read at the first read and at each probe. An unknown key is kept and
  noted, a plugin that cannot load is noted, never an error. `brain tui --tab` now takes a plugged project's tab too.
- `public.deny.repos` generated from the scope tree (`wi-brain-deny-from-tree`), opt-in by `config.json`
  `public.deny_from_tree: true`: the projects under a class floor of `private` or stricter, set by a container of
  `scopes.yaml` or by the project's own `classes: {floor}` in `projects.yaml` (which also binds its stores), join with
  their repos' names (a repo of `public.repos` left out) the hand list that `brain check --public` and the public guard
  read, so a newly placed private project is denied without a hand edit; `brain scopes --deny` prints them. With it
  on, a tree or registry that cannot be read, a named tree file missing, no tree, or an error of the tree's check makes
  the public guard refuse.
- `docgraph/v1`, the documentation graph's neutral contract (`wi-brain-docgraph-contract`,
  [docs/docgraph.md](docs/docgraph.md)): a public, versioned JSON format any program may emit for a project's
  documentation graph (decisions, documents and sections, milestones, criteria, items, changes, tests, threats,
  modules, owner decisions, findings and the needs of later phases), normalised statuses, edges named as the Brain
  names them (`constrains` with its compatibility included), a source on every node and derived edge, declared links
  with their reason and `confirmed`, and the findings of sixteen named checks with their meaning. Its schema is
  `schemas/docgraph.schema.json`, registered with the other formats, with an invented document of each side of the
  version in `tests/fixtures/formats/docgraph/v1/`; it evolves by the status contract's rule (optional keys added in
  v1, a new type, status or meaning is v2; `release-check` counts an optional key added to its schema as a patch, the
  owner's answer of 2026-11-12). Nothing in it assumes code: a `change` is any reviewed modification, and a producer
  with no code (a research or writing project) emits the same nodes. `brain docgraph validate FILE...` checks a
  document against it (exit 1 when invalid or written for a later version) and `brain docgraph checks` lists the
  named checks; neither needs a brain.
- Reading the documentation graphs of the projects a brain only reads (`wi-brain-docgraph-read`,
  [docs/docgraph.md](docs/docgraph.md), « Reading several documents »): `brain docgraph pin PROJECT --from CLONE
  --ref REF --file PATH` copies an `access: read` project's docgraph/v1 document from a local clone at a commit (`git
  show`, never a checkout), validated, to `docgraph/PROJECT.json` under the brain's root with the commit it was read
  at (`pinned`), committed by PR; the registry entry is unchanged. `brain docgraph join` reads the brain's own graph,
  the pinned copies and the documents the brain keeps for itself as one docgraph/v1 graph, ids namespaced by project
  (`item:example/25`; an edge names another document's node as `item:@example/25`), and runs ten named checks again
  across it, the producers' findings of the other checks kept; exit 1 when a document is left out or an error is found. `brain check` in a
  brain's own root warns on a document under `docgraph/` the join leaves out, and `brain reference` gives each pinned
  project a page under `docs/reference/read/`.
- The documentation graph (`wi-brain-docs-graph`, [docs/docs-graph.md](docs/docs-graph.md)): for a store with the
  `Doc` type, a catalogue of every doc file (its Diataxis kind, `generated` and `dated-spec` apart, its last commit,
  its owner when the doc declares one in its first lines, the nodes it cites, the docs that cite it), declared
  `depends_on` links between doc sections with their `props.reason`, and `doc.stale` at section level: a hand-written
  doc whose cited node changed (its YAML entry) or whose declared parent was committed after its own last commit.
  `brain sync` writes the generated view `notes/docs_graph.md`; `brain check` warns on the docs to re-read and on a
  declared link without its reason; `brain audit --diff` adds an info line `doc.reread` for each doc a change does not
  touch that cites a node it edits; `brain docgraph emit` writes it as a docgraph/v1 document. A brain made before
  can add `notes/docs_graph.md merge=brain` to its `.gitattributes` and the view's `generated` side to
  `boundary.yaml`, as `brain init` now writes them; until then the view merges as plain text.
- Each format as a released engine wrote it (`wi-brain-format-fixture-freeze`): `installer/freeze_store.py` also
  freezes each registered format's file the tag's engine wrote, `tests/fixtures/formats/<format>/v<N>/<tag>.<ext>`
  (ar, config, ddr, event, packs, projects, sr, template; from v0.2.4 and v0.3.1), and `tests/test_formats_frozen.py`
  reads each one strict. `--only-formats` and `--reuse` freeze them alone from a kept freeze. The status document is
  never frozen (a machine's inventory). The engine's own tests only: nothing changes for a brain.
- A signal no longer cuts a write: every command runs under `brain.shutdown.graceful()`, so SIGINT, SIGTERM, SIGHUP
  and Ctrl+Break stop it once the ledger line or the atomic state write in progress is whole, with its `finally`
  blocks run and its locks released; stderr names the signal and the command ends by it (POSIX) or exits 128 + its
  number (Windows). The interactive
  cockpit (`brain tui`) and the scheduled alerts pass (`brain alerts --notify`) run once per machine
  (`<BRAIN_HOME>/locks/`): a second cockpit is refused, a second pass skipped (`wi-brain-graceful-shutdown`).
- Graph templates as layers (`wi-brain-graph-templates`): research_graph's catalogue of the layers real stores have
  proven (work, decisions, records, lessons, ideas, research, data, code, docs_tests, features, operations, fleet,
  rules, delivery), each a layer file with its types, edges and their endpoints, statuses, mode, commands, views,
  checks, GitNexus projection and fictitious examples. `research_graph layers` lists them (and the store's), `show`
  one, `compose` the schema.yaml they make (`templates:` records each layer's version, `endpoints:` the edges'
  allowed types), `add` layers to a store by a plan (a diff of schema.yaml that keeps its text and comments, then
  `--write`), `propose` the layers a typology's stage proposes; `research_graph init --layers` composes a new store's
  schema. `research_graph check` refuses an edge outside its declared endpoints (a schema without `endpoints:` is
  checked as before). A `brain init` template's graph may give `layers:` (the catalogue's and the template's own
  `layers/<name>.yaml`) instead of `schema: default`. The brain's base schema and research_graph init's default are
  unchanged: a test keeps them equal to their layers composed.
- **`brain handover write|check|root`** (`wi-brain-handover-command`, `brain.succession`): the coordinator's hand-over
  note in `<BRAIN_HOME>/handover/`, its own app id first; the Remote Control guard's hand-over conditions checked
  before the calls, with the predecessor an incoming coordinator archives first; and the chain root, the owner's mark
  in their own terminal (`<BRAIN_HOME>/handover/roots.json`, refused to a session by the guard): a root the owner
  started and marked hands over without a coordinator's name, and the coordinators it starts pass the parent
  condition through it.
- `brain handover write --successor NAME` also writes the successor's brief beside the note, `<note>.brief.txt`, its
  first line carrying the word `ultracode` (ultracode on at every coordinator hand-over, the owner's decision of
  2026-11-12); `brain handover wait --successor ID` waits, bounded (default 120 s, at most 600), for the successor's
  first turn before Remote Control on for it, and says to wait again and retry once on a refusal that says it is
  unknown (`wi-brain-handover-command`, its follow-up).
- Item sizes: `brain item add --size S|M|L|XL --size-reason "..."` gives a work item `props.size` and
  `props.size_reason`, the writing session's judgement (S under about 0.3 h of active time, M about 0.8 h, L about
  2 h, XL beyond: to split); `brain item set ID size=...` checks the scale; `brain item add` stamps a work item
  `props.created` and, without a size, prints the line that gives one; `brain check` warns on an open item written
  since then without a size, and on a size without its reason (`brain.sizing`, `wi-brain-item-size`).
- `brain health ipc` (and `--all`; `wi-brain-local-ipc-auth`, `brain.ipchealth`): whether the Brain's local services
  bind loopback and require the machine's token where they can check one, and whether their containers run as a
  user. It checks the token file, the MCP
  server's 401 without the token, and each running container of the Brain's Compose projects and code index (FAIL for
  a port published beyond loopback, a warning as root), and names what takes requests without the token. Under
  `--all` it is silent, probing nothing, on a machine that never made the token and requires none.
- The collector can require the machine's token, opt-in: config.json `ipc.require_token: [otel-collector]` (a new
  optional key, with `ipc.mcp_port`); `brain bundle apply` then renders otelcol-contrib's `bearertokenauth` on every
  OTLP receiver and mounts the token as a secret. Claude Code's export needs
  `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>` then (docs/mcp.md, « The Brain's other local services »).
- One machine identity and facts in three states (`wi-brain-machine-facts`): `brain.machine.name` (`$BRAIN_MACHINE`,
  else the host name) read by the memory sync, the profile and the schedules; an anchor on the OS
  install (a sha256, never the raw id) kept in `<BRAIN_HOME>/machine.json` and checked against `config.json` `hosts`
  (a reused name, a cloned image, a renamed machine or a copied home is a doubt `brain doctor` names, which holds the
  memory export); facts true,
  false or unknown (an unknown fact holds neither way in `recommend_when`); ECC and battery probes; `ecc`, `battery`
  and `encrypted` flattened; each fact's source in `brain doctor` (an infra agent's report behind the new `infra-node`
  capability, off by default; the local probe; a nodes file read at a git ref; `hosts`) and `<BRAIN_HOME>/facts.json`;
  `profile.json` merged key by key over `tier.components`; `config.json` `engine.min`, under which the memory export and
  the DDRs write nothing. New optional config keys: `hosts`, `engine.min`, `inventory.nodes_file`,
  `inventory.agent_json`.
- The guards in the MCP server (`wi-brain-mcp-guards`, `brain.mcpguards`): every tool call of `brain mcp serve` is
  judged before it runs, since other clients run no Claude Code hook. A write tool must declare its effect (a
  `brain` command, a file written) or it is refused; the owner's own `brain` gestures (answering a decision, a
  schedule installed, the machine's token or vault keys made, the engine updated, stacks started, `--arm`) are refused
  whatever the tool; a write's arguments pass the secret scan; then the engine's guards judge the effect, strictly (a
  check that cannot judge refuses, and `BRAIN_GUARD_ALLOW` lifts nothing there). Refusals go to the guards ledger as
  `mcp:<tool>`. `brain.guards.refusals` takes `strict=True` for it; the hooks stay fail-open (docs/mcp.md, « The
  guards »).
- `brain mcp serve` (`wi-brain-mcp-server`): the Brain as an MCP server, in the foreground of whoever launches it.
  Resources: the neutral source's rules, the procedures' files, the decision log's index and one ADR by template;
  prompts: the procedures; tools: the graph's reads (`brain items`, `item show`, `adr show`, `spec show`, `next`),
  `brain check`, the memory notes read and a proposed memory note the memory sync carries by a reviewed PR. Every
  answer passes the secret scan. stdio by default; `--http`: Streamable HTTP on a loopback address only, each request
  with the machine's token. `brain mcp tools` lists the tools. A versioned container definition
  (`packages/brain/container/`: a user that is not root, the port published on 127.0.0.1 only, never restarted by
  itself) builds the image; running it is the owner's decision (docs/mcp.md).
- `brain ipc token [--init]`: the machine's token for the Brain's local services, `<BRAIN_HOME>/ipc/token`, made
  once by `--init` and never printed (docs/mcp.md, « The machine's token »).
- The merge gate (`wi-brain-merge-gate`): `brain merge-ready PR` answers, at zero token, whether a PR may be merged:
  open and not a draft, main not moved under a file it touches since their merge base (a green CI on a stale base is
  not the merged tree; a rename counts by both names), `brain merge-check` on the head against that merge base (a
  head that merged an older main included), every CI check green on the head, the
  review's stamp for the head with no finding open, the public check's stamp for a repo of `public.repos`, nothing
  `brain check --public` refuses in the PR's title and body. Exit 0, a stamp under `<BRAIN_HOME>/merge-ready/` and
  the head to merge (`gh pr merge --match-head-commit`), else exit 1 and the list of what blocks. The new engine store `merge-ready` (`$BRAIN_HOME/merge-ready`, sealed, derived) holds the stamps.
  `brain merge-check`'s check takes the head to read (HEAD by default, as before). See
  docs/merge-driver.md.
- `brain mod list | show | enable | disable | explain` (`wi-brain-mod-command`): the module face of `brain profile`
  on the same files. `config.json` `tier.components` and `profile.json` accept the module ids of the store's registry,
  expanded to their capabilities (a capability named directly wins). `tiers.yaml` capabilities gain `depends_on`
  (hard: pulled at enable, a needed one refused at disable unless `--cascade`) and `uses` (soft). `enable` and
  `disable` print the plan and the cost, and `--apply` writes this machine's `profile.json`. `explain` shows each
  layer (the preset, config.json, profile.json, the dependencies pulled, the scopes' capabilities as declared).
  `brain init` writes an empty `modules` key.
- `brain init`'s three screens (`wi-brain-modules-installer`, `brain.firstrun`), offline and with no telemetry: who
  you are (`--preset`: a preset of the brain's catalogue, Lite, Default or Recommended, or a persona of a private
  catalogue/v1 file, `--catalogue FILE`, on its base preset), your machine (the probe's facts and, per module, whether
  it runs here, its requirements and its RAM, VRAM and disk against the machine, and whether its `recommend_when`
  holds; an unknown fact is said, never assumed), adjust (`--with`, `--without`: each module's box, its cost, its
  hard dependencies pulled, what must be downloaded; a module the machine does not hold, a core or auto one, a
  planned one or one a module on needs is refused). `--interactive` (`-i`) asks the screens in a terminal and ends
  on the same choice as one command. The choice is brain commands, shown in the plan and, with `--apply`, run in
  order after the files and logged in `<BRAIN_HOME>/ledger/setup-<month>.jsonl`: `brain profile set BASE --apply`,
  then `brain mod disable ID --apply` for each module of the base left out (those that need another first), then
  `brain mod enable ID --apply` for each one added; a second apply changes nothing. A distribution to download (a
  pip extra) is named, never fetched. `--tier` now defaults to the preset's base (default for Recommended, frozen
  for the machine by brain profile set). Without these flags `brain init` is as before, and its plan names them.
- The cockpit's Modules page (`wi-brain-modules-tab`, SIGMA-15), in the settings tab: each module of the brain's
  catalogue (catalogue/v1) with its state on this machine and its source (`brain mod list`), its cost, what it needs and
  its fallback, then the distributions read-only. Enter on a module asks on or off (`--cascade` too), shows
  `brain mod enable|disable`'s plan, then `y` writes this machine's `profile.json`, logged as the owner's; off keeps the
  module's data and configuration. `brain tui --once --tab settings` prints the page.
- The old-store fixture (`wi-brain-old-store-fixture`): `tests/fixtures/stores/<tag>/brain/` holds a brain as a
  released engine wrote it through its own commands (v0.2.4, before the Lesson type, and v0.3.1), and
  `tests/test_old_stores.py` runs this checkout's `brain check`, `sync`, `record check`, `item`, `items`, `lesson` and
  `retro` on each, strict. `installer/freeze_store.py vP` freezes the last tag's store, and the version PR's
  `release-check` refuses a version without it (docs/release.md, « The fixture freeze »). For a brain, one change:
  the scout and the Doc links leave a frozen store (`tests/fixtures/stores/**` in any test folder) out of the docs
  set and the shape signals, so a README under such a folder is no longer a Doc node after the next `brain sync`;
  nothing newly refused.
- A JSON Schema for `permissions.yaml` (`wi-brain-permissions-schema`): `schemas/permissions.schema.json` describes
  what `brain.permissions` reads (its sections, a rule's keys), a test keeps it in step with the module's constants and
  the fixtures, and it is registered so that `brain schema diff` and `release-check` compare it like any format's
  schema. It refuses nothing at run time: `brain.permissions` still reads the file itself. A first schema given to a
  format the last tag registered with none is a patch's (`release_check.new_formats`).
- The ranked frontier: `brain next` lists each wave's groups by the owner's priority (a confirmed one before the same
  one proposed), then the owner's order (`props.order`), then value over effort (WSJF: the value derived from the
  features delivered, a milestone moved and the items unblocked, or the owner's `props.value`; the effort from
  `props.size`); the wave's quick wins (size S, high value) come first; `brain next --explain` shows each score's parts
  and the values the owner set; the cockpit's frontier takes the same order, sorts by score and offers Size, Value and
  Score columns (`brain.ranking`, `wi-brain-prioritization`).
- A project's own formats (`wi-brain-project-formats`, spec-brain-data-compat § 3, the owner's PF-1 answer « Opt-in
  run »): `projects.yaml` `formats:` registers each persisted format of a project (id, glob, repo, class, version,
  schema, fixtures, a `check:` command in any language that exits 0 or 1, its timeout) and `migrations:` the glob
  check of its database migrations (`when`, `add`, `repo`). `brain check` judges the declarations always (the shapes,
  then, where the checkout is here, a glob that matches, a schema and a fixtures folder that exist); the commands run
  only by `brain formats check` (or `brain check --formats`): with no shell, bounded (default 120 s, `--timeout`), a
  pass or a fail cached in `$BRAIN_HOME/formats/<project>.json` (a new store, sealed, derived) by the hashes of the
  command and of the files it judges, `--fresh` to rerun. `brain formats list` prints them. The scout (`brain audit
  --diff`) finds a `when` file changed with no file added for an `add` glob: a NEW `format.migration` finding, or a
  `Justified: <path>: <reason>` line. An older engine notes the two keys as a newer brain's and keeps them (in CI:
  refused): a registry declares them once every machine runs this release.
- A project's brain by profile (`wi-brain-project-templates`): `brain init --template cli|local-client|service|
  data-pipeline|research [--stage prototype|mvp|v1|scale]`. Each is the generic brain, its files unchanged, plus the
  profile's standards selection in `projects.yaml` (`standards: {profiles, stage}`), the CI jobs (the tests with
  their coverage, compat-prev: the last tag's tests on the PR's code), the test harness (a virtual clock, fault
  injection, the old formats' fixtures, with its own tests), the format registry's skeleton (`docs/formats.md`), an
  issue template and an ADR template, the boundary's rule for `.github/`, and the graph's layers for the profile.
  A template may `extends` one of the engine's and `append` a fragment to a file the base writes; the bases
  `_project` and `_software` are what the profiles extend. This adds to what `brain init` can write: the release
  that carries it is a minor one.
- `brain check --public --refresh`: `brain check --public --history` in every local checkout of a public repo (the
  registry's repos whose remote is in `config.json` `public.repos`), by the running engine; a HEAD whose stamp is
  still valid is left (`same`), a checkout with tracked changes not committed is skipped and named, one with findings
  is named and not stamped. `brain update` runs it with the engine it just installed, and the installer's `-Apply`
  does too (its `stamps` step), so the push guard no longer refuses the push of each checkout's HEAD after an upgrade
  until the owner re-checks it by hand (another local branch still asks its own check); a finding or an older command
  is said, never an install failure
  (`wi-brain-public-stamp-refresh`).
- The technical reference's arc42 skeleton (`wi-brain-reference-arc42`, [docs/views.md](docs/views.md), « The
  technical reference »): `docs/reference/README.md` now holds the twelve arc42 sections, each from its source in the
  graph, every statement with its status and its id: goals and the pending milestones' triggers, constraints from the
  rules (the decisions that set them, what enforces them), context from the registry, the solution strategy and its
  key decisions, the building blocks (the module pages), the runtime view (hooks, workflows, skills, plugins, MCP
  servers), the deployment view (the project's stacks), the specs in force, the decisions by module, quality as each
  milestone's trigger, its items and their tests (the goals with no test counted), risks and debt (blocked items, debt
  items, open lessons, open questions), and a glossary. The prose a person writes lives in `docs/reference.yaml`
  (`schemas/reference.schema.json`, a new format registered with the others: `goals`, `strategy` and `glossary`
  required; a short intro per section and per module optional); a required field missing fails `brain reference`
  (nothing written) and `brain check` once the reference is kept. The public render takes the goals, strategy and
  glossary of the public repo's own `docs/reference.yaml`.
- The technical reference as of a point (`wi-brain-reference-asof`, [docs/views.md](docs/views.md), « The reference
  as of a point »): `brain reference --asof POINT [--out DIR]` renders it as of a wave (its id or release), a
  milestone or an era (the commit of the day it was reached; a pending one as of now, with its target view: its
  trigger, the features and items planned in it), a date or a git ref. The store, the DDR records, the modules
  registry (another store's included), `docs/reference.yaml` and `projects.yaml` are read from git at that commit
  (nothing checked out), and the README gains « Changes since » the wave reached before: decisions taken and
  reversed, features whose status changed, items done, modules added. It is written under
  `BRAIN_HOME/views/reference/<project>/<point>/`, never into the repo. The reference's section 3 now reads the
  repo's `projects.yaml` from the file itself, so a rendering as of a commit reads that commit's.
- `brain schema diff --against <tag>` (`wi-brain-schema-diff`): what a change of the JSON Schemas and the graph
  stores' `schema.yaml` narrows (a property removed, a field newly required, an enum or a type narrowed, a bound
  tightened, `additionalProperties` closed, a node type, an edge type or a status removed), and whether the PR's
  `Compat:` line resolves it (`Compat: migration <id>` with the format's `v` bumped and its fixture, or
  `Compat: breaking <adr-id>`). The scout (`brain audit --diff`) shows it as a `schema.narrowed` line: an info line by
  default, NEW under the new optional config.json key `audit.schema_diff_strict`. CI's advisory `schema-diff` job runs
  it on every pull request (docs/formats.md, « The schema diff »).
- `--scope REF` (a node of the scope tree and its subtree; `global` is `--all`) on `brain queue`, `tui`, `usage`, `cost`
  (estimate, review, audit), `audit` and `permissions`, as on `status`, `resume` and `digest` (`wi-brain-scope-tree`);
  `brain permissions --requests --scope` keeps its meaning, a level's start.
- The scope tree as data (`wi-brain-scope-tree`): `parent:` places a project of `projects.yaml` (a read-only project
  and a tenant mount too) under a container of the new optional `scopes.yaml` (beside `config.json`; `config.json`
  `scopes`, `$BRAIN_SCOPES`) or under another project; `config.json` `scope_types` renames or adds a type of the
  catalogue. `brain check --all` checks the tree (a known parent, no cycle, ids unique across projects and containers,
  a known and accepted type, a class floor never under an ancestor's, a warning past six levels); `brain scopes`
  prints it; `brain status --scope REF` shows a node's subtree (`global` is `--all`), and so do `brain resume` and
  `brain digest`; `brain sync` writes
  `notes/scopes_graph.md`. Without `scopes.yaml` and `parent:`, everything stays flat under Global, as before.
- **The standards registry's consumers** (`wi-brain-standards-registry-consumers`), for a project that declares
  `standards:`: `brain review prep` adds a standards lens of its `review-lens` rows (`brain standards lenses`);
  `brain audit` measures `standards.gap` (P2, never in the scout; ruleset 10), a row whose check covers neither a
  repo's language nor a slot its `tools:` declares; `brain standards rules` prints its `rule` rows as rules text;
  `brain standards ci` prints a GitHub Actions skeleton from its `check` and `measure` rows with an adapter.
- **The background waiter's hint** (`wi-brain-stuck-waiters`, `waithint.sh`, `brain.waithint`): a Bash or PowerShell
  call run in the background whose `until` or `while` loop has no deadline, no process check and no check that its
  file is still there gets one line of hook context (bound it, exit when the file or process is gone, stop the
  background tasks before the cleanup), never a refusal; `BRAIN_WAIT_HINT=0` turns it off. The brief's after-merge
  lines and close-item's step 5 add: no background task left at the cleanup or the archive (the app refuses to
  archive a session with live work).
- Targeted tests (`wi-brain-targeted-tests`): `brain test --changed [BASE]` selects the test modules a change touches
  by the store's coverage map (`coverage/<repo>.json`, or `--map FILE`) and runs them first: the tests that ran a
  changed module's functions or import it, and those of its importers, transitively; a changed test, or a
  `conftest.py`'s folder; the tests that start a Python process. Fail-safe: no map, a dirty or foreign one, a file
  coverage cannot see (docs, data, a shell test), a module the map never measured or a deleted one widens the answer
  to the whole suite, and static evidence only adds a test. It starts
  in shadow mode: the selection runs, a widened answer is left to the CI's whole suite, and each run is a line of
  `<BRAIN_HOME>/ledger/targeted-tests.jsonl`; `--strict` runs the whole suite when the answer widens, `--list` and
  `--json` print the selection, `--inert GLOB` declares paths no test reads. See docs/tests-graph.md.
- **`BRAIN_TEST_ROOT`** (`wi-brain-test-speed-2`): one folder (made absolute) for the bulk of the brain suite's
  temporary files: pytest's temporary folders under `<root>/tmp` (`PYTEST_DEBUG_TEMPROOT`, so pytest keeps its
  numbering and its last three runs; an explicit `--basetemp` wins) and the harness tests' venvs under
  `<root>/venvs`; unset, the system's temp folder as before. The engine's own scratch files, git's and pip's still go
  to the system's temp folder. A short folder keeps pip's paths in those venvs under Windows' length limit and is one
  place an owner can exclude from an on-access antivirus scan (about 10 % of the suite's time measured with pytest's
  temporary folders excluded); the engine never changes the antivirus (`packages/brain/README.md`, « Tests »).
- **`BRAIN_TEST_WORKERS`** (`wi-brain-test-speed-2`): the number of workers `pytest -n auto` (or `-n logical`) starts
  for the brain suite (`tests/conftest.py`, xdist's `pytest_xdist_auto_num_workers`), the strict form of xdist's
  `PYTEST_XDIST_AUTO_NUM_WORKERS`, which it wins over; unset, xdist decides as before, and an explicit `-n N` wins.
  Measured on a 16-thread Windows machine without psutil (`-n auto` = 16), three runs each with the machine shared: 16
  workers 229/308/281 s; 24 workers a crash at start on one run (a worker's platform query timed out with 24 starting
  together), then 262/237 s; 32 workers 259/257/246 s. No clear gain, so nothing changes by default.
- The cockpit's settings tab (the comma, `wi-brain-tui-settings`): every setting with its value, the file or variable
  it comes from and how it changes, page by page (Cockpit, Identity, Brain, Permissions, Setup; `brain.settings`).
  The cockpit's own settings in `<BRAIN_HOME>/tui.json` are edited there with Enter and apply at once: the theme, the
  timezone, the language, each panel's free title, and two new ones, `refresh` and `probe` (how often the files are
  checked and the probes run; `--refresh` and `--probe` now win for one launch only). The brain's settings (identity,
  `$BRAIN_HOME`, `config.json`, the registry, the engine pin, the profile, the stacks, the notification routes, the
  code index, the scope types, `permissions.yaml`, Claude Code's settings) are shown with the command that changes
  each and never written from there; a secret is named, never shown. `brain tui --once --tab settings` prints the
  pages.
- The cockpit's setup wizards (`wi-brain-tui-setup`), on the Setup page of the settings tab (`brain.wizards`): the
  first run (the profile Lite, Default or Recommended), the stacks to enable, the modules, a project to add, the
  notification channels (ntfy, Telegram and its chats, the routes), the permissions, the machines, the code index, a
  new brain from a domain template, Claude Code's settings and the checks. Each is the brain's own commands, never a
  hidden edit: its choice, its exact command with its plan run first, then the apply on `y`, run as the owner's,
  logged in `<BRAIN_HOME>/ledger/cockpit-<month>.jsonl` and refused in a Claude Code session's shell. Claude Code's
  settings, a project added to `projects.yaml` and a permission granted stay a plan with the owner's command; a
  secret is never typed there, only named.

### Fixes

- `brain update` and the installer no longer verify a release tag whose ref was pointed at another release's signed
  tag object (an account that can push but holds no key, rolling the machines back to an older signed tag): the
  signature covers the tag object, not the ref's name, so the object must now name the tag itself and a commit;
  otherwise the verdict is `misnamed`, refused under `engine.verify_tags` (`wi-brain-install-verify-tag`).
- The capture ledgers (`ar`, `ddr`, `events`), the guards, queue, answers and cockpit ledgers, the quota readings,
  the session starts, the notify audit and its held messages are appended under their folder's lock, in one write, as
  the exec ledger is: sessions' hooks writing at once on Windows no longer lose or mix lines; a hook still on an
  older engine writes without the lock until its plugin is updated (`wi-brain-ledger-append-lock`).
- **A coordinator's successor just started gets its Remote Control at the handover** (`wi-brain-rc-handover-starting`).
  The guard's `handover-on` case (and `handover-off`'s successor test) refused a successor the outgoing coordinator
  switched on seconds after `start_session`: it had no transcript yet, so its state read `unknown`. A successor in the
  desktop app's session files, not archived, started by the caller, with a coordinator name and no transcript yet
  now counts as starting when its own app file's `createdAt` is at most 10 minutes old (`HANDOVER_START_S`); an older
  one, or one whose `createdAt` cannot be read, stays refused. Nothing else is widened (docs/guards.md, « Remote
  Control's three exceptions »).
- `brain audit` and its scout (`brain audit --diff`) no longer hold the technical reference's generated pages to
  `doc.links` and `doc.dead-ref` (`wi-brain-reference-scout`, audit ruleset 9): a doc whose first lines open with
  ``GENERATED by `brain reference` ``. Nothing in such a page is fixed by hand: a module page with no feature or item
  names no node, and a quoted title may name another repo's path; its sources are the graph's. The scout refused a
  brain's first commit of `docs/reference/` for them. Every other doc is checked as before, a generated README
  included (its text is the repo's `readme.yaml`).
- **Three tests that failed under load are fixed, not retried** (`wi-brain-test-speed-2`).
  `test_sessions::test_a_masters_earlier_transcript_raises_no_alert`: the test rewrote the app's file with a cli id of
  the same length, and on NTFS the second write could land in the same mtime tick, so `sessions.app_index`'s cache
  (by size and mtime) kept the earlier metadata; the tests' `app` fixture gives each rewrite a newer mtime.
  `test_memory::test_hook_scripts_end_to_end`: the fake gh holds the detached job at a gate the test opens once the
  hook has returned, instead of a 10 s bound a loaded machine overran. The docker-marked
  `test_docker_compose_config_accepts_the_rendering` waits 120 s for a cold docker client, not a check's 15 s.
  Fewer git processes per run: `test_release_check`'s tagged repo is made once per worker and copied, and
  `make_repo.commit` reads the new sha from the branch's ref file (`conftest.head_sha`).

### Changes

- `brain perf --usage` lists apart, with how each is reached, the commands that never run from the CLI by design: a
  command module's `RUNS_VIA` declares a subcommand wired (a hook, another command or a schedule runs its code:
  `brain capture`, `brain decision announce` and `view`, `brain docs check`, `brain memory sync`) or run on demand (the
  vault's, the spool's and the identity's owner gestures, `brain memory status`, `brain down`, `brain standards show`,
  `brain docs render`); they are no longer gaps, nor make their feature unused. The close-item procedure's step 2b
  now runs `brain cost review <id> --record` after the retro, and `--record` no longer writes a zero review on an item
  no session of the token ledger served (it prints `not recorded: <id>`) (`wi-brain-adoption-gaps`).
- The installer says whether it runs from the commit the signed tag names (`verify   this installer runs from that
  commit`, else a `note` with its own HEAD and `+changes` when tracked files differ): the tag's check runs inside the
  tag's own code, so it cannot vouch for that code; a statement, never a refusal. `docs/identity.md` (« Signed
  releases ») gives the offline checks a brain's own bootstrap runs on its engine clone before running it: the tag
  annotated and signed by a key of `allowed_signers`, the clone's HEAD its commit, no tracked file changed
  (`wi-brain-install-verify-tag`).
- **The parallel tests steal work** (`wi-brain-test-speed-2`). `pytest -n auto` with no `--dist` now schedules with
  pytest-xdist's `worksteal` (`tests/conftest.py`; pytest-xdist 3.5 or later, pinned in the CI): an idle worker takes
  tests still queued on a busy one. Measured on a 16-thread Windows machine, alternating runs: the idle
  worker-seconds at the end of the run fell from about 400 to about 125 and the workers' utilisation rose from 88 %
  to 96 %, with the wall time unchanged (233-236 s against 236-247 s). On that machine the suite is bound by process
  creation (some 10,400 git calls, about 55 git starts per second at most), so busier workers wait longer per git call.
  `--dist load` gives the old scheduling back.
- The typology doors kept open before the release (`wi-brain-typology-pretag`, spec-brain-typology-packs E1, E1 bis,
  E1 ter). The project base `_project` writes nothing of a code host: the GitHub issue template and the boundary's
  `.github/**` rule move to `_software`. `research` extends `_project` and takes the parts of `_software` it uses by a
  new template key, `takes: {an engine template: [the brain's paths]}`, instead of extending all of it. Every
  template's output is unchanged (a test hashes each one). A pack key of `source/packs.yaml` this engine does not
  know is kept and noted in read mode, refused only in strict mode (CI), as a top-level key already was, so a later
  brain may add pack keys (`typologies`, `layers`...). The README says that the templates' profiles and stages and
  the graph layers' `lifecycle` ids follow one typology catalog still to come, and that an unknown id is tolerated.
- `brain update` installs the new version beside the running one, in `<BRAIN_HOME>/venvs/vX.Y.Z` (a venv made from
  the interpreter the active one was made from), runs a health gate there (`brain --version`, `brain doctor --quick`
  in the brain's root, the guards letting `git status` pass), and only then switches `<BRAIN_HOME>/venv`, now a
  link to the active slot (a junction on Windows, a symlink elsewhere), which the launcher on the PATH follows; a
  watchdog runs `brain --version` through both after the switch and switches back to the previous slot when one
  fails. The first
  such update moves the installer's real `venv` folder into `venvs/v<its version>`. Three slots are kept. The hooks,
  the installer and the shim keep reading `<BRAIN_HOME>/venv`; a new home store, `venvs` (sealed, install), is
  declared (`wi-brain-update-blue-green`; the layout of `ddr-2026-11-12-blue-green-engine-slots`).

## 0.3.2 — 2026-11-11 — Standards, contracts and resilience

### Upgrade

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.

Nothing to run for the rest. What this release could newly refuse or newly run is off until the owner turns it on, each
an optional key, default off: `engine.verify_tags` (signed release tags), `session_archive.enabled` (the session
archive, which also needs gitleaks), `integrity.sidecars` (sha256 sidecars of the truth-local stores), `modules.store`
(a module registry read in another store) and a project's `standards:` in `projects.yaml` (the standards it follows).

### Added

- The module registry's map of realisations (`brain.modulemap`): a `modules.yaml` entry can carry hand-written
  fields beside the document ones (`wanted`, `capabilities`, `depends_on`, `uses`, `ai`, `realized_by` with each
  realisation's project, kind, what, paths, ref, licence, state, contract, ships_in and retire, and `map_review`),
  described by the new registered format `schemas/modules.schema.json`. On the store that keeps the registry,
  `brain modules --check` (exit 1) and `brain check` (a warning) validate an entry that carries `realized_by` or
  `map_review`, and only such an entry: its shape, the module ids it names, the capabilities (`tiers.yaml`), the
  projects (the projects registry), the paths of a realisation that exists at their ref when the project's
  checkout is on the machine, a wanted module with neither a realisation nor an open item; a wanted module with no
  item done or open and no realisation that exists, 90 days after its `since`, is a warning. The view gains the
  realisations, the map's gaps and the declared dependencies still to classify, and `brain modules --json` gains
  `map` and `map_problems`. A registry with no entry that carries the map, and its view, are unchanged.
- `brain perf --usage [--since 28d] [--top N] [--json]`: command adoption at zero token (`brain.adoption`). The CLI
  registry crossed with the engine's exec ledger (runs per command and subcommand, split into those a session typed
  and the others: a hook, a scheduled task, a script; the commands that never ran), with a mini scan of this
  machine's transcripts (hand reads of a brain's graph, decision logs, journals and views that a read command
  answers; hand edits of the files a command writes) and with the features (a have feature whose commands never
  ran). Each gap comes with what to propose: the read hint, a hook wiring, a procedure line, or wire, document or
  retire; nothing is refused (`wi-brain-command-adoption`).
- `brain <project> <subcommand> ...`: a project's command plugin, named under its `plugin` key in `projects.yaml`
  (reserved until now), runs its subcommands (`brain.plugins`). The value is an entry point of the group
  `brain.plugins` or `module:attr`; the plugin is a command module (`register` and `run`, as brain's own) or a
  callable `main(argv)`, so a project's own CLI plugs in unchanged and stays a shortcut of `brain <project>`.
  `brain --help` lists the plugged projects without importing them; a plugin that cannot load fails its own run only
  (exit 2); `brain check --all` reports a `plugin` that is neither empty nor a string and a project named like one
  of brain's commands, whose plugin would never run. A registry without the key, or with `plugin: null`, behaves as
  before (`wi-brain-command-plugins`).
- External formats under contract (`wi-brain-external-contracts`, docs/formats.md « External formats »): the capture
  hook counts the keys of Claude Code's hook payloads it does not know or misses, and the Stop hook the transcript
  records of an unknown type or without a key it reads, in `ledger/contracts.json`; a first sighting goes to
  `errors.log` and the next SessionStart health names it once, and nothing is refused. The status document that
  `brain doctor --json` prints is published as `schemas/status.schema.json`, a new format (`status`) with its fixtures
  in `tests/fixtures/formats/status/v1/`: any contract id of config.json `inventory.schema`'s pattern, default
  `brain.status/v1`. Real-shaped fixtures of each captured hook payload and of a transcript are in
  `tests/fixtures/claude/`.
- Negative controls for the stranger test's harness: `stranger_test.py --fault rewrite|truncated-ledger|unreached|wrong-engine`
  injects one fault into the upgrade test, and `pytest -m harness` (CI's `harness-controls` job, on a pull request that
  touches the harness) requires each a no-go at the step that guards against it, and the run without a fault a go; a
  test refuses an engine workflow step that writes a command substitution to `GITHUB_OUTPUT` without testing that it is
  not empty (`wi-brain-harness-negative-controls`; docs/formats.md, « Negative controls »).
- The hook contract between the bash hooks and Python (`wi-brain-hook-contracts`, docs/formats.md « The hook
  contract »): `brain sync` renders `hooks/contract.txt` beside the plugin's hooks (config.json's rules and the
  engine's version as flat lines), which `inject-rules.sh` reads instead of the first `"rules"` array in config.json's
  text; the budget and announce `.mark` files and `cache/node-clis.txt` end with a format line that today's bash
  checks (another format starts Python), after the lines an older plugin copy reads, so its bash keeps working; each
  hook passes its `brain_version` to Python, and the SessionStart health says when the session's hooks and the engine
  differ. Every hook now spells `<BRAIN_HOME>` as Python does on Windows (`%USERPROFILE%\.brain` before `$HOME`), and
  the health says when two `.brain` folders exist.
- Integrity of the engine's truth-local state files, opt-in (config.json `integrity.sidecars: true`, or
  `BRAIN_STATE_INTEGRITY=1`; off by default): each save through `brain.stateio` writes a sha256 sidecar beside the
  file (`<name>.sha256`: the hash, size and mtime) and each load checks it. A file whose size and mtime match but whose
  hash does not (bit rot) is set aside with a note (the copy kept, never saved over); one another writer changed since
  (an older engine) loads and gets a fresh sidecar; a missing sidecar loads as before (`wi-brain-integrity-checks`).
- Language adapters (`wi-brain-lang-adapters`, [docs/standards.md](docs/standards.md), « Language adapters »): a repo
  declares the reports its own tools write in a new optional `projects.yaml` key, `repos[].tools` (`{lint|typecheck|
  test|coverage|format: {report, format, tool}}`; formats SARIF, JUnit XML, Cobertura, lcov, coverage.py's JSON,
  istanbul's summary); `repos[].lang` does not change. The engine reads the reports and runs no tool. `brain audit`
  measures a new check, `lang.report` (P2, ruleset 8), for a repo that declares `tools:` only: a report missing or
  unreadable, no test run, failed tests, lint, type or format findings, coverage under 50 %. The scout,
  `test.coverage` and `test.links` still read Python only. `brain standards check` counts a
  standard whose `adapter` slot a repo declares as covered on that repo's language. A repo without `tools:` is read
  as before: nothing is newly refused. An older engine notes `tools` as an unknown repo key (refused in CI's strict
  mode), so the key lands in a registry once its CI runs this engine.
- The module map reads the features and the done items too (`wi-brain-module-backfill`): in a store with
  `modules.yaml`, `brain modules` counts how many features and done items carry a `props.module` (the view's new line,
  `--json`'s `features`, `features_unplaced`, `done_items`, `done_unplaced`, `warnings`), and `brain check` warns,
  never fails, about one with no module, `none` without its reason, or a module the registry does not know;
  `brain modules --check` lists them as warnings, its exit code still the open items' only. The public render of
  `FEATURES.md` never shows the Module column (the module ids are the owner's platform's): a public `FEATURES.md` an
  earlier engine rendered with it, and `notes/modules_graph.md` (its new line), are stale until the next `brain sync`.
  The technical reference reads these modules.
- The module registry can be kept in another store and imported from the platform's documents
  (`wi-brain-module-registry-import`). `config.json` `modules.store` (optional, default none) names the store of the
  projects registry whose `modules.yaml` a store without its own reads (`<project>:<store>` or a project's name;
  only the stores under `config.json`'s folder): its items keep their module checks, and its view names that
  registry. An imported entry (`source` a list of documents, or `imported` a day) is validated by
  `brain modules --check` and warned of by `brain check`: its document fields, the documents read with their dates,
  the day of the import, the dependencies it declares; a hand entry is checked as before. The view of a registry with imported entries gains
  the generated counts (in the tree, proposed, by brick), the documents read and the divergences the import
  reported; `brain modules --diff [REF]` says what changed since the registry at a git ref (modules added and
  removed, document fields and hand fields changed). The engine never reads the documents: an agent session writes
  the import. A registry with no imported entry, and its view, are unchanged. Turning `modules.store` on is the
  owner's opt-in to the module checks on the stores that then read it: their view is written by the next
  `brain sync` (stale until then, an error of `brain check` under `views.strict`).
- **External calls retry, then step aside** (`wi-brain-net-resilience`). One helper, `brain.net`, now carries the
  engine's calls to GitNexus (its API and MCP endpoint), docker in `brain index`, the ntfy and Telegram channels and
  `git ls-remote` (the update check, `brain tidy --remote`): a read that fails quickly (refused or reset, a DNS
  miss, an HTTP 429/502/503/504) is tried again twice with exponential backoff and full jitter, a POST only when it
  was surely not handled (refused, 429, 503: nothing is sent twice), a timeout never. A call that finds its service
  down (a timeout, a connection that still fails) opens the service's circuit breaker for 5 minutes
  (`<BRAIN_HOME>/net/breakers.json`, store `net`, sealed, truth-local): its next calls are skipped at once and said
  in one line, so a service that is down costs one timeout per window. An HTTP status is an answer and never opens
  it; `brain update` reads the tags even with it open; `BRAIN_NET_BREAKER=off` tries every call for a run. A call
  that succeeds behaves as before.
- **A failed notification waits in the outbox instead of being lost** (`wi-brain-outbox`). When no channel delivers
  because none was reached (refused, a DNS miss, HTTP 429/503, its breaker open), `brain notify send`, a blocking
  decision's notification and an alert's `resolved` message are kept in the sealed local outbox
  (`<BRAIN_HOME>/outbox/queue.json`, store `outbox`, sealed, truth-local) under an idempotency key made of their
  content: queued once, dropped when the same message is delivered later, replaced by a newer message of the same
  key. A timeout or a reset is not queued (the message may have arrived). Every alerts pass sends what is due again,
  after 5 minutes, then twice as long each time (at most 6 h, full jitter), and gives an entry up after 12 tries or
  7 days. A refusal (HTTP 401) is not queued; nor is an open alert (the pass already sends it again) or the quiet
  mode's summary (it stays held). `brain notify status` says how many wait.
- Generated READMEs (`wi-brain-readme-sync`): a repo opts in by holding `readme.yaml` at its root (a new format,
  `schemas/readme.schema.json`: what the repo is, why, how to start, its notes, the commands its README quotes).
  `brain docs render [--write [--force]] [--repo R] [--dir PATH]` writes its `README.md` from the engine's template
  and the facts of their sources (the features recap with a link to the repo's `FEATURES.md`, written too; each
  quoted command's usage from its `--help`; a private repo's active specs, recent ADRs and pending milestones), a
  public repo's render neutral. `brain docs check` exits 1 when `readme.yaml` misses a field, a quoted command is
  gone, or `README.md` is not the render; `brain check` runs it (a stale README is a stale view), `brain audit`
  measures `readme.yaml` and `help.quoted` in an opted-in repo, and close-item renders and checks it. A repo without
  `readme.yaml` is never read: nothing is newly refused. An existing `notes/audit.md` changes its not-measured lines
  (`readme.yaml` and `help.quoted` say « not opted in », `help.quoted` now for every repo) at its next
  `brain audit --write`.
- The release preview: CI's advisory `release-preview` job runs `release_check.py --preview --base origin/<target>` on
  every engine PR, the version policy applied as if the next release were a patch of the last tag. It names the
  registered schemas that moved since that tag and the pending Upgrade fragments' steps beyond the standard ones, says
  « a patch » or « a minor » and which reasons the PR carries, in the job's summary, and exits 0 whatever it says.
  `release-check` now also refuses, on every PR, a standard step that two pending Upgrade fragments ask, so a PR's
  fragment never copies the standard steps again (`wi-brain-release-preview`, docs/release.md « The release preview »).
- Signed engine releases (STD-3): `brain update` and the installer verify a release tag with `git verify-tag` before
  installing it, against the keys of `members.yaml`'s new `releaser` role, through `allowed_signers`, a file
  `brain identity allowed-signers --write` generates beside `config.json` (namespace `git`; the installer reads the
  file, `brain update` the keys themselves when the brain has a `members.yaml`). After the install, the commits pip
  recorded are compared with the one the signed tag names (a tag moved meanwhile is said). Both say the verification
  either way and refuse nothing by default; `config.json` `engine.verify_tags: true`, an optional key, refuses an
  unsigned tag, one signed by another key, or one that cannot be verified. `brain check` warns when `allowed_signers`
  is no longer what `members.yaml` gives. CI's `release-tag` job says whether the tag is signed, advisory. The release
  checklist signs each tag (`git tag -s`, docs/release.md « 3. The tag »); the owner's key and its setup:
  docs/identity.md « Signed releases » (`wi-brain-release-signing`).
- `brain session-archive run [--dry-run] [--max N]`, opt-in (`session_archive.enabled` in config.json, off by default;
  no scheduled task is created): the agents' transcripts (Claude Code's sessions and their subagents, quiet for 2
  hours, changed since archived) copied line by line with each row a residency filter matches replaced by a stub
  (`session_archive.resident`, `{name: regex}`: the owner's patterns, the engine names no source), scanned by the
  engine's secret patterns then by gitleaks, each line it reports dropped and a second pass required clean, then sealed
  into the spool (`brain.spool.put`, store `session-archive`, class sealed, a new engine store) and indexed by session
  record in `$BRAIN_HOME/session-archive/index.json` (machine of origin, the session's place in the tree, what was
  dropped). gitleaks absent or failing: nothing is archived. `--dry-run` lists what would be archived and dropped and
  seals nothing. `brain session-archive status`; `brain health session-archive` gives the age of the last archive
  (`wi-brain-session-archive`).
- The software catalog of the standards registry (`wi-brain-standards-catalog-software`, `catalogs/software.yaml`,
  [docs/standards.md](docs/standards.md)): 90 standards for code products in ten domains (architecture, code
  quality, concurrency, persistence, distributed systems, security, testing, release, observability, data governance
  and developer experience), each with its profiles, the stage it is required from, how it is enforced and by what
  check, the languages that check covers and how the Brain itself meets it. Every row is proposed until the owner
  validates its domain. A project follows them only once it opts in (`projects.yaml` `standards:`): nothing is
  newly refused.
- The standards registry (`wi-brain-standards-registry`, [docs/standards.md](docs/standards.md)): standards as data,
  one row per standard (its domain, statement, the profiles it applies to, the stage it is required from, how it is
  enforced and by what check, the languages that check covers, how the Brain itself meets it, proposed or
  validated), in catalogs of a new format (`schemas/standards.schema.json`, `v: 1`): the engine's own under
  `src/brain/catalogs/`, and a brain's local ones that a project names. A project opts in with a new optional
  `projects.yaml` key, `standards: {profiles, stage, include, exclude, catalogs}`. `brain standards list|show|check`
  reads them (`check` exits 1 on a broken catalog, an id found twice or an unknown profile, stage or id, and lists
  the applicable standards whose check does not cover a repo's language); `brain check --all` checks every
  project's `standards:`, and `brain brief` lists the project's applicable standards as its invariants. A project
  without the key follows none: nothing is newly refused. A brain older than this one notes `standards:` as an
  unknown key (refused in CI's strict mode), so the key lands in a registry once its CI runs this engine.
- `brain spool push`, run by hand: the sealed local spool of the stores that leave the machine (`$BRAIN_HOME/spool`,
  a new engine store, class sealed). It seals each changed store of its set (`spool.stores`, else the ledger, the
  usage and the session records) through `brain vault` after a secret scan, refuses a store whose class never leaves
  the machine, seals a store again when its recipients change, sends what waits to `spool.remote` when one is set (a
  folder), each copy checked by sha256, and keeps the last 3 snapshots per store. `brain spool status` and `verify`;
  `brain health spool` gives the age of the last push without an error. The `spool` block of config.json is optional
  and additive; nothing runs until a first push (`wi-brain-storage-split`).
- The technical reference, generated (`wi-brain-technical-reference`): `brain reference [--write]` writes
  `docs/reference/`, an index of the modules of the store's `modules.yaml` and one page per module (what it does from
  its features; the decisions in force on its nodes, from the answered DDRs with the earlier ones folded, an ADR no DDR
  went to by its title, a superseded one marked; the rules its items deliver, its specs, items done and open, open
  questions), and counts the decisions no module holds; without `--write` it exits 1 when the folder is not the
  render. Once the owner opted in (`brain reference --write`: the project's own render in `docs/reference/`), `brain
  sync` writes it again and `brain check` warns when it is stale on the default branch; a brain without it is not
  concerned, and a page there that is not generated is never overwritten. `brain reference --public --repo R --out DIR` renders a
  public repo's neutral reference by feature domain from its features only, written only when
  `brain check --public` would refuse none of it; the engine's own is in `docs/reference/`.
- `brain wave plan [X.Y.Z] [--at-once N] [--hot NAME]... [--json]`: a wave's lots at zero token (`brain.lots`). The
  open items whose predicted surface (`brain collisions`') shares a file go into one lot, run in the order of their
  `depends_on`; hot files (READMEs, CHANGELOGs, `formats.md`, `FEATURES.md`, `config.schema.json`, `changes/`) are
  counted apart. A lot that holds another's prerequisite comes a round earlier, the lots that unblock the most first,
  at most the sessions cap in force less the master's and the PRs verified at once (3) a round. It prints the
  predicted conflicts, the hot files shared, the items with no known surface and what the memory guard and the last
  quota forecast say now, and refuses nothing; `brain next` shows the current wave's first round
  (`wi-brain-wave-lot-planner`).

### Fixes

- `changelog.py compile` puts a blank line before a fragment that is not a list when it follows another in the same
  section, so a closing Upgrade paragraph such as « Nothing to run for the rest » no longer joins the last numbered
  step; a list after a list still continues it (`wi-brain-changelog-prose-fragment`).
- `brain` no longer raises `UnicodeEncodeError` when its output goes to `NUL` on Windows (`brain items --text x >
  NUL`): `NUL` reports `isatty()` true in the ANSI code page, so the CLI now switches stdout and stderr to UTF-8 with
  `errors=replace` whenever a stream's encoding is not UTF-8, not only when it is not a terminal; a UTF-8 console is
  left alone (`wi-brain-nul-stdout-encoding`).
- `brain retro --wave` reads the numbered waves: `--wave 0.3.2` (or `wave-0.3.2`) takes the items `part_of` that
  wave and those carried to it by `props.carried_to` (not those carried out of it), with the items whose free-text
  `props.wave` names it, a comma after the release included (`0.3.2, week of ...`); the deep retro of 0.3.1 found no
  item. It also lists the retro notes recorded on the wave's items (`props.retro_notes`, a `notes` key in `--json`)
  (`wi-brain-retro-numbered-waves`).

### Changes

- The three append-only files that grew with no retention are logs of their own now (`stateio.LOG_RETENTION`):
  `usage/starts.jsonl` (the governor's brainstorm starts, 2 months) and `usage/quota.jsonl` (the quota readings, 12
  months) rotate monthly into `<stem>-YYYY-MM.jsonl` like `errors.log`, and the notifications' audit
  (`notify/YYYY-MM.jsonl`) drops the months past 6. `quota.load_readings` reads every monthly file, the governor the
  live file and the newest month, so the month's turn hides nothing (`stateio.log_files`). An older engine after a
  rollback reads only the live file: less history, and its `--observe` may ask for `--resets` until a weekly
  reading is noted again (`wi-brain-logs-unclassified`).
- The read hint starts only on a likely hit (`wi-brain-read-hint-matcher`): its hooks in the core plugin's
  `hooks.json` are split per tool, each Read, Bash and PowerShell hook gated by an `if` condition naming the brain
  files it hints about (`Read(//**/journal.md)`, `Bash(*decisions.md*)`...), so a call that names none starts no
  bash at all; Grep's path is a folder or a glob, which a permission rule cannot match, so a Grep call still starts
  it. The rules do not overlap: a call that names one brain file starts it once. Before, every such call started
  bash (on one machine, 4,854 of 4,981 runs in a week stopped at its fast path, about 85 ms each on Windows). The
  conditions only narrow: the bash fast path and the Python hint decide as before, and the hint stays opt-in
  (`config.json` `hints.read`); `brain sync` renders the new `hooks.json`.
- Before `brain permissions render --write` writes a settings file of a git work tree (a project's
  `.claude/settings.json`, its untracked `settings.local.json`), it backs the file up under
  `$BRAIN_HOME/backup/<project>-<key>/<its folder>` (the sealed backup store, keyed by the repo's path; the last 10
  copies per file, none when nothing changed), never as a `.bak` beside it, so git status stays clean; an untracked
  `.bak` an older engine left beside it moves there too. `~/.claude/settings.json` is backed up beside itself as
  before (`wi-brain-settings-backup-home`).
- An edge of a store listed after its project's first may name an ADR or SDR stub that first store derives (an item
  of a second store `decided_by` an ADR of `notes/decisions.md`): `brain sync` and `brain check` accept it and
  research_graph resolves it in the first store, as any edge between stores (`--foreign-store`). The 0.3.0 rule that
  refused it (« that ADR stub is notes/graph's only ... move the edge ») is dropped, with its error: it only stops
  refusing (`wi-brain-shared-root-stub-rule-drop`). An engine before 0.3.2 still refuses such an edge: write one only
  once every machine of the brain runs 0.3.2 (`brain update`).

## 0.3.1 — 2026-11-10 — Opt-in guards, read commands and identity

### Upgrade

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.

Nothing to run for the rest. What this release could newly refuse is off until the owner turns it on in
`config.json`, each an optional key, default off: `usage.guard.memory_available_gb` (the RAM floor),
`usage.guard.session_hour_measured`, `views.strict`, `hints.read` (the read hint), `audit.norm_lints_strict`,
`audit.feature_coverage_strict`, `features.public_strict` and `identity.require_signed`. A brain that writes
`members.yaml` adds its `boundary.yaml` rule (docs/identity.md).

### Added

- `brain audit` checks the feature coverage, at zero token (check `feature.coverage`, `brain.feature_coverage`,
  ruleset 6): in a package whose `commands/` lists its own modules (a command registry), each command module (not the
  `_` helpers) and each module beside its `cli.py` must be named by a feature, by an active `implemented_by` CodeRef
  of its file or by a title that says it (`brain quiet`, `brain.stateio`). The full audit lists the ones no feature
  names as info, never counted, in a section per repo (`feature coverage: N of M ...`, the JSON key
  `feature_coverage`, a section of `notes/audit.md`). The scout (`brain audit --diff`) makes one the change adds a NEW
  line and one already there that it touches a DEFER line to the repo's debt item; nothing that passed is newly
  refused (`feature.links` already makes an added unit no feature names NEW). `config.json`
  `audit.feature_coverage_strict` (a boolean, default false) is the owner's opt-in: true, the touched one is a LEFT
  line to fix in the PR (`wi-brain-audit-feature-coverage`).
- Edges between the stores of one registry (`brain.crossstore`): an edge may name a node another registered store
  holds. brain gives research_graph the stores that hold the ids a store's edges name (`--foreign-store`, on every
  run and in-process load: sync, check, the views, the pending questions, `brain impact`), so the store loads and its
  board and roadmap show the other store's node by its id and store (`wi-x (parent:notes/graph)`); `brain item link`
  and `brain item add` accept another store's id as one end. `brain check --all` counts the edges between stores and
  refuses one whose end is in no store of the registry on this machine, as the store's own check already did; without
  `--all` a brain's own root warns of it. A store whose edges name only its own ids runs as before
  (`wi-brain-cross-store-edges`).
- Dependency probes, loud fallbacks (`wi-brain-dependency-probes`, `brain.depprobes`): `config.json` `probes`
  declares a token-free probe per external dependency of a capability, with the machines it runs on, of four kinds
  (`file-age`, `json-age`, `command` with no shell and its output never shown, `http` with no header and its URL
  never shown), each with its own timeout (a command past it is killed with every process it started, and a probe
  still running never holds the process at its exit). The alerts pass runs this machine's probes when the brain's own project is
  in scope and raises `probe:<name>` at the probe's level for each one that is not OK (sent once, resolved once, by
  the pass's notify path); each run is recorded in `<BRAIN_HOME>/probes/state.json` (state, last OK, since).
  `brain status` shows a probes row once one runs here, the cockpit's health panel a line; `brain probes [--last |
  --list | --kinds] [--json]` runs or lists them; `brain config --check` checks the declarations.
- The feature matrix split by repo: each repo's `FEATURES.md` lists the features whose `repo` it is, and a checkout
  that is a clone of a public repo (one of its git remotes is in `config.json` `public.repos`) gets the public render
  (`brain features render --repo R --out <checkout>/FEATURES.md --write`): a feature's new optional props
  `public_title` and `public_id` stand for a title or an id that names the owner or a private project (the graph
  keeps both), only the repo's own code, tests and docs are shown, and no spec, ADR or work item of the private
  brain; the render warns about what `brain check --public` would still refuse in it. `brain audit` (check
  `features.md`) compares each repo's file with its own render, public or not, and its fix names the `--repo`/`--out`
  command for a repo other than the store's; in a public clone that check accepts the full render too, unless the new
  optional `config.json` key `features.public_strict` is true (the owner's opt-in, default false: nothing that passed
  is newly refused). `brain features set` checks a `public_id` is a feature id no other node
  or feature has (`wi-brain-features-repo-split`).
- Identity, standalone (`wi-brain-identity`): `members.yaml` beside `config.json` declares a brain's people (their
  `person_id`, public SSH ed25519 signing keys and age recipients), accounts, organizations and tenants, and their
  roles per project or tenant (`schemas/members.schema.json`). An answer of the owner-decides class (money, keys,
  accounts, visibility, heirs, scheduled tasks) may carry a detached signature, `records/ddr/<id>.sig`, made in the
  owner's own terminal with `ssh-keygen -Y sign` (namespace `brain-decision`) and verified by `brain check` with a
  decider's public key; the engine never signs nor reads a private key. New command `brain identity check | unsigned
  [--write DIR] | payload ID | attach SIG|DIR`. The board marks an owner-decides answer `(signed)` when its signature
  verifies, `(signature not verified: brain identity check)` when it does not, else `(unsigned, relayed by session
  S)`, and `asked.by` names the asking session, else the owner: never `unknown`. Nothing is
  refused by default: without `members.yaml` nothing is checked, and with it the findings are warnings until the
  optional `config.json` `identity.require_signed: true` makes them errors (docs/identity.md). Writing `members.yaml`, add its
  rule to `boundary.yaml` (personal side, docs/identity.md).
- `brain audit --diff` reads four cheap norms in the AST of each Python file a change touches (`brain.norms`, ruleset
  7): `norm.timeout` (a subprocess call or `urlopen` without `timeout=`, a `Popen`'s `communicate()` or `wait()`
  without one), `norm.encoding` (a text `open()`, `read_text()` or `write_text()` without `encoding=`),
  `norm.naive-time` (a naive `datetime.now()`, `today()` or `utcnow()` stored as text, in a dict or a JSON dump) and
  `norm.secret-argv` (a token, password, secret or API key variable in a child's command or env). What a change adds
  is an info line, never blocking, and a NEW line under the optional `config.json` key `audit.norm_lints_strict:
  true`; the occurrences already in a touched file are DEFER lines to the repo's debt item, one per file and norm
  (`wi-brain-norm-lints`).
- Read commands, so sessions stop reading a brain's files by hand (`brain.reads`): `brain item show ID [--history]`
  (the item's props in full, its edges both ways, the ids its props name, its blockers, the ADRs behind it (direct,
  inherited, superseded) and its specs, the DDRs that name it; `--history` its changes from git), `brain items` with
  filters (`--status`, `--all`, `--priority`, `--wave X.Y.Z|ID`, `--milestone`, `--prop K[=TEXT]`, `--text`,
  `--type`, `--repo`, `--limit`), `brain adr show REF [--titles]` (an ADR's text by id, title or the start of its id,
  else the ADRs that decide a node such as a rule), `brain spec show REF [--section N | --toc]` (a Spec node, a Doc id
  or a path) and `brain journal last [N] [--titles]`; each takes `--json` and loads the graph in brain's own process
  (no `research_graph` on the PATH). A PreToolUse hint (`readhint.sh`, `brain.readhint`), never a refusal: when Read,
  Grep or a shell command that reads targets a registered brain's graph YAML, decision log, journal or generated
  views, one line of hook context names the command that answers; bash builtins until the call names one of those
  files. The hint is opt-in (about 0.2 s per Read and Grep call, which had no hook before): `brain render --target
  claude` (`brain sync`) registers it in the core plugin's `hooks.json` only when `config.json` says
  `"hints": {"read": true}` (a new optional key, default false: not registered, no call pays its cost); while it is
  on, `BRAIN_READ_HINT=0` turns it off in a session. The close-item procedure, the brief (`brain brief`, « How to start ») and
  the generic `CLAUDE.md` template name the commands (`wi-brain-read-commands`).
- `brain usage` shows the subagents and the workflow agents apart (`wi-brain-usage-workflow-agents`). Their
  transcripts (`<session>/subagents/agent-<id>.jsonl`, `<session>/subagents/workflows/<run>/agent-<id>.jsonl`) were
  already read with the session that launched them and counted in its cost. Each ledger row now also says whose that
  cost is (`agents`): the plain subagents by label (the `description` of their `.meta.json`), and each workflow run by
  its id, with its agents, days, phases and labels (the meta's, else the run's `journal.jsonl`; a label written once
  the agent's transcript stopped growing is read at the next scan). `brain usage` prints
  the split between main threads, subagents and workflows; `--by workflow` lists each run with the session that
  launched it, `--by agent` each agent's label, and the summary adds the workflow runs when there are any. A message
  that a subagent's transcript holds is counted once, as the subagent's, even when the parent's transcript copies it.
  `brain usage quota` adds the cost of a session-hour over the last 7 days, the agents' cost included (`session-h`,
  kept in `quota.json`), as information. The usage guard's parallel-sessions cap uses it only when you opt in with
  config.json `usage.guard.session_hour_measured: true` (default false), and then when it is above
  `usage.guard.session_hour_usd`: on a machine whose sessions run workflows, that cap is lower and a new session can be
  refused where it used to pass. By default the cap keeps the configured `session_hour_usd`, so nothing that passed is
  newly refused. `brain usage guard` shows the measured value and whether it is applied (its `session-h` line), and a
  `sessions` refusal names the session-hour it used. The ledger's scanner is now `SCAN_V` 3, so the next
  `brain usage` scans every transcript still on the machine again.
- `brain views`: one writer of the generated views (`brain.views`, `docs/views.md`). Without a flag it lists the
  views git tracks (a `GENERATED by` marker in their first lines or a `_generated_` name, as the merge driver knows
  them), where the checkout stands, those changed or staged here and those the merge driver kept from one side
  (`--json`). On a branch, `--unstage` takes the staged views out of the index after `git add` (the working tree keeps
  them for the branch's checks) and `--reset` puts every view back at HEAD before a merge of the default branch (a
  deleted view included). `--write`, in a worktree at the default branch's tip (refused in a main checkout), runs brain
  sync's writes, the audit view (`--no-audit`: not) and brain check by the default branch's strict rules (whatever
  `views.strict`), lists the files it changed and, with `--commit`, commits those alone, never when its check fails
  nor when HEAD lacks `origin/<default>`'s tip (fetched first unless `--offline`); it refuses another engine than the
  pin unless `--force`, and its flags without `--write`. To use it, after each merge: from a worktree at the default
  branch's tip (`git worktree add -b chore/views-<date> <path> origin/main`), `brain --root <path> views --write
  --commit`, then push and merge that commit; a branch may then leave its views uncommitted. A brain worked on its
  default branch itself regenerates there with `brain sync`, as before. A branch that still commits its views keeps
  working: the merge driver's view kind stays the fallback. The scout (`brain audit --diff`) no longer asks a branch
  for a fresh `FEATURES.md` (its check `features.md` is `never` in the scout): the full audit and the default
  branch's check do (`wi-brain-views-one-writer`).
- `brain check` (and `brain refresh`, which checks) say the stale generated views by where the checkout stands: on
  the default branch (HEAD on origin/HEAD's target, else main, else master) a warning naming `brain views --write`, for
  the decision queue, the links graph, the plan and module maps, and now the records' graph, `FEATURES.md`, the kanban
  and the roadmap; on any other branch one `views:` line, no longer a warning; outside git the warnings as before.
  Nothing newly refuses by default (`wi-brain-views-one-writer`).
- `config.json` `views.strict` (a boolean, default false): how an owner opts in to the one writer's rules. True,
  `brain check` and `brain refresh` exit 1 on a stale view on the default branch, and `brain audit --write`,
  `brain coverage --write`, `brain features render --write`, `brain decision view --write` and `brain modules --write`
  refuse another engine than `config.json` `engine.pin`, as `brain sync` does (`--force` writes anyway). Before
  setting it, check the main checkout (`brain check`) and, where it names a stale view, regenerate from a worktree at
  its tip with `brain views --write --commit`, then merge that commit (`docs/views.md`; `wi-brain-views-one-writer`).

### Changes

- Finished sessions archive themselves (`wi-brain-archive-after-merge`). The close-item procedure's step 5 says the
  session that merges its own PR archives itself once its after-merge steps are done (the main checkout pulled, the
  backlog ticked, the journal note written, its report given: the archive is its last act), the owner's standing
  authorization standing for their yes; a coordinator archives its children as soon as a report says merged and
  verified, without asking again; never another running session (the self-archive is the one mid-turn archive
  allowed, the final tool call of the merging session's turn) or one with uncommitted, unmerged or unverified work;
  and the owner's app setting `auto_archive_inactive_days = 7` is the token-free net, which the owner sets and no session
  changes. `brain brief` gains an « After the merge » section with the same clauses (`brain.brief.AFTER_MERGE`;
  config.json `brief.after_merge` replaces them, `[]` drops the section), and the generic rules template counts the
  archived session in its definition of done. Tests check that the procedure, the brief and the template keep saying
  it.
- Every store the engine writes under `$BRAIN_HOME` has a class (`wi-brain-classes-home-stores`, COMPAT-6):
  `brain.classes.ENGINE_STORES` grows from 6 to 35 (usage, budget, forecast, announce, handover, inbox, features,
  cache, memory-sync, schedules, alerts, notify, secrets (secret), the telemetry collector's data, stacks, telemetry,
  code-index, code-map, public-check, reviews, backup, tui.json, update.json, personal.json, profile.json,
  code-index.json, venv, bin, the engine's tag clones), each with a suggested data class and a format class
  (truth-local, log, derived, install, external). An engine store a brain does not declare is no longer an error of
  `brain check --all` and `brain classes --check`: it takes its suggested class (never looser than sealed), the check
  notes it, and `brain classes PATH` and `classes.decide` use that default. A name at the top of `$BRAIN_HOME` that no
  store covers is noted, sealed by default. `brain classes --suggest`, for a brain that already declares classes,
  prints only the engine stores it misses; `brain init` declares them all. `brain classes` lists the sources the
  engine reads and never writes: the desktop app's session metadata, read through a closed list of keys (never
  `lastTurnReport`, `pendingSystemReminder`, `promptAppendSnapshot`, `remoteMcpServersConfig`, `spawnSeed`), its
  worktrees and its shared notes. A test fails on a name the engine's code writes under `$BRAIN_HOME` that the list
  does not hold, and another on a text key of the app's metadata reaching a store.
- The usage guard's memory check reads two measures (`wi-brain-memory-guard-two-measures`): it refuses a new session
  or a workflow when committed memory reaches `usage.guard.memory` % (default now 97, was 90) or, once the owner sets
  a floor, when the available RAM falls under `usage.guard.memory_available_gb` GB (new; default 0, no floor, so
  nothing that passed is refused; 4 is a sensible floor). Its refusal, `brain usage guard` and
  `brain status` (a new `memory` row) show both measures and name the one that refuses. Committed memory alone (what
  Windows promised, RAM plus page file) refused every start at 93-96 % while a third of the RAM was free. The
  governor's settings cache now keys on the defaults, so an upgrade never keeps the old cap.
- `release_check.py`: a format the last tag did not register (its own `SCHEMAS`) none of whose files exists there
  (a format this version adds, `new_formats`) is reported on its own line and is a patch's; a file new to a format
  that exists, or a format whose files are renamed, still moves it (`wi-brain-release-schema-additive`).
- `release_check.py` reads config.json's schema structurally (`wi-brain-release-schema-additive`): optional keys
  added to `config.schema.json` (none of them `required`) and prose changes no longer make a format move, so a patch
  may hold them; it reports them as grown. Any other change of it, and any change of a record schema (ar, ddr, sr,
  event), still makes the release a minor one (docs/release.md, « The version policy »).
- **Nothing to run for the machine-local state** (`wi-brain-state-safe-io-rest`): `tui.json`,
  `memory-sync/state.json`, `vault/device.json`, the session files under `sessions/` and the budget watch's states
  gain `"v": 1` at their next write, which an older engine reads unchanged. Each may now have a `<name>.bak` beside
  it, and one that was unreadable a `<name>.unreadable-<stamp>`: both are safe to delete once looked at.
  `ledger/errors.log` now moves aside each month as `errors-YYYY-MM.log` (kept six months); an `errors.log.1` left by
  the old 1 MB cut can be deleted. `install.ps1 -Apply` stops on a `~/.claude/settings.json` that is not a JSON object
  (« fix it by hand first ») instead of failing in the middle of its writes, and leaves `settings.json.bak` beside it
  at each write.
- **The rest of the machine-local state goes through `brain.stateio`** (`wi-brain-state-safe-io-rest`,
  spec-brain-data-compat N4; `docs/formats.md`, « Machine-local state »): a backup beside the file, an atomic synced
  write, an unreadable file set aside by the next write, a newer brain's file read but never written. It now carries
  the cockpit's `tui.json` (the keys this engine does not know are kept through a save; `brain tui` says when a newer
  brain's file keeps it from remembering the views), `memory-sync/state.json` (a newer record stops the sync before
  any fetch, in `last.json` and the alert), `vault/device.json` (`device init` and `forget-previous` refuse a newer
  file before the keystore is touched; `device init --rotate` keeps the keys a newer brain added with the same `v`),
  the Stop hook's session snapshot and state, the end-of-turn report, the plan file and the budget watch's
  `budget/<session>.json` (a newer one is left to its brain, the mark set ahead so bash starts no Python meanwhile;
  the prune takes the backups too). A symbolic link is written through: the file it points to changes, the link
  stays.
- **A foreign file is edited in its own keys only**: `brain.stateio.read_foreign` / `write_foreign`, and through them
  `permissions.ClaudeCode.write` (`brain permissions render --write`, `--level session --out`), refuse a settings file
  that cannot be read or is not a JSON object (never replaced) and one Claude Code wrote meanwhile (run again), back it
  up beside itself unless git keeps it as it is (`permissions.kept_by_git`: tracked and unchanged; a gitignored
  `settings.local.json` is backed up), then write atomically. `install.ps1` writes `~/.claude/settings.json` with the
  same policy (`Read-ForeignJson`, `Write-ForeignJson`; an empty file is read as a missing one).
- **The log class**: `ledger/errors.log` moves aside each month, or past 1 MB, as `errors-YYYY-MM[-n].log`, kept six
  months (`brain.stateio.rotate_log`, which never moves a log over a rotated one when hooks rotate at once);
  `stateio.LOG_RETENTION` holds each log class's retention (errors 6 months, the engine's timing 3, the ledgers of
  records kept), and `brain.selftime` prunes through it.

## 0.3.0 — 2026-11-10 — Sigma's home, waves and eras

### Upgrade

From 0.2.8, in this order. This release newly refuses what passed (a project's second store beside its first, a
project at a shared root without its own files, an edge of a second store to a root ADR stub, an `access` value other
than read or write), so it is a minor version, 0.3.0 (`docs/release.md`, « The version policy »). The formats' schemas
do not change (`access` is an additive key of `projects.yaml`, a milestone's `kind` an additive prop of the store, whose
`schema.yaml` stays as it is), but two registered files of what `brain init` writes once (`store` in `SCHEMAS`) do:
`gitattributes` and `boundary.yaml` gain a line each for the new view `notes/plan_graph.md`, which alone would make it
a minor version, and 0.3.0 is one already; `release_check.py` names them. A brain made before keeps its own files:
step 4 adds the two lines. `brain sync` (run by `brain update`) writes that view in a store that holds a wave or an
era, and nowhere else. Steps 1 to 4 apply only where the brain has what they name; do them before installing, since
`brain update` runs `brain sync`.

1. **Move an edge of a later store to a root ADR stub**, where a project lists more than one store. A store after its
   first derived the ADR and SDR stubs of the root's decision logs, as its first store does (every store ran with
   research_graph's defaults); it now covers no decision log (`--no-decisions`), and `brain sync` empties its
   `_generated_decisions.yaml`. An edge of it to one of those stubs (an item of it `decided_by` an ADR of
   `notes/decisions.md`) no longer resolves and fails `brain sync` and `brain check`, each naming it (« that ADR stub
   is notes/graph's only »): move such an edge to the first store or remove it, and drop the `shared_ids` waiver of
   the stub, which turns stale.
2. **Give a project at a shared root its own files**, where the registry lists two projects at one root. The second is
   loaded only once it declares its own `stores`, `journal` and `decisions` (the defaults are the first's files);
   until then no command runs it. `brain check --all` says what to declare, and `brain --project <it>` says why it is
   not loaded.
3. **Give a store beside the first a folder of its own**, where a project's second store sits beside its first (both
   under `notes/`): `brain sync` refuses that store until it has one, since its board was written over the first's.
4. **Add the plan view to `.gitattributes` and `boundary.yaml`**, in a brain that 0.2.8 or older initialised, by hand
   (`brain init` keeps the files it made earlier): `notes/plan_graph.md merge=brain` to `.gitattributes`, and
   `- {glob: "notes/plan_graph.md", side: generated, why: "brain sync (brain.waves: eras, milestones, waves)"}` to
   `boundary.yaml` (a store's view beside its other views elsewhere: the same lines at that path). Until then the view,
   which `brain sync` writes again whenever an item of a wave changes, merges as plain text, and two sessions in
   worktrees conflict on it, as the merge driver exists to prevent; `boundary.yaml` reads it as `notes/**`.
5. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
6. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
7. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.
8. **Wait for every machine before an `access: read` entry or a shared root**: such an entry lands in a registry only
   once every machine that reads it runs brain 0.3.0 or later. An older brain (0.2.8 and before) notes the unknown key
   `access` (in CI, under `BRAIN_STRICT`, refuses it) and reads the entry as a full project, at the registry's root
   with the default store, journal and decision log (`docs/formats.md`); a project that shares its root with another
   gets its board written over its owner's by an older brain.
9. **Wait for every machine before the first wave or era**: a store gains one only once every machine that writes it
   runs brain 0.3.0 or later. An older brain reads a wave or an era as a plain milestone: its `brain milestone
   suggest` may propose putting an item under an era (which the new `brain check` refuses), and its `brain sync`
   leaves `plan_graph.md` stale (a warning on the newer machines). `brain wave import --from X.Y.Z` (the next
   release) makes the waves from the items' `props.wave` without turning a release already tagged into a pending wave.

Nothing to run for the rest.

### Added

- **Waves and eras: the plan as one generated tree** (wi-brain-waves-as-releases, wi-brain-eras; brain.waves). A
  Milestone may carry `props.kind`: `wave`, named by its release (`props.release: X.Y.Z`, `props.week` optional), its
  members work items by `part_of`, itself part of a milestone or an era; `era`, its members milestones, its exit the
  Go/NoGo question asked as a DDR once they are reached (`props.exit`, `props.stage_to` and `props.serves` optional).
  `brain check` refuses a malformed or repeated release, a wave holding a milestone, an era holding an item, an item
  in two waves, a `props.carried_to` that names no later wave, a `props.carried_via` that names no wave, and a dropped
  wave that still holds an open item (planned there or carried into it: no live wave would show it); it warns about
  a reached wave that still holds one (the version PR's closure check still refuses it), a wave in no milestone or era, an era without its exit and one whose exit is due
  (`docs/formats.md`, « Milestone kinds »). `brain sync`, its one writer, writes `notes/plan_graph.md` beside the
  store's other views: era > milestone > wave > items, each item with its status and what waits on the owner (its
  `props.open`, its `external_blocker`, the pending DDRs on it), each wave's carried items first, then the startable
  ones; `brain check` says when it is stale. `brain next [--json]` prints the current wave (the lowest release not
  closed): its carried items first, its startable items, what waits on the owner, the other open ones, then the next
  wave, at zero token. The version PR closes its wave (`docs/release.md`, « 1. Before the version PR »): `brain wave
  close X.Y.Z [--carry-to X.Y.Z] [--drop ID]... [--write]` carries each open item by name (`props.carried_to`, to a
  pending wave only, created beside the closed one when that release has none yet; an item carried again keeps the waves it went through in `props.carried_via`) or drops it, then
  reaches the wave, and refuses while one is neither; `brain wave check X.Y.Z` is the rule alone, and
  `release_check.py --store DIR` refuses a version PR whose wave breaks it or is not reached yet (exit 2 for a
  `--store` it cannot read; it imports brain and research_graph from the checkout). `brain wave add X.Y.Z [--parent
  MS]` adds a wave at once, with no DDR (unlike `brain milestone add`: a wave is named by a release, which the owner's
  version PR closes); `brain wave import [--from X.Y.Z] [--write]` proposes a wave per release the items' free-text
  `props.wave` names, from `--from` on (the earlier ones, already tagged, listed and left out), and lists the other
  values for the owner to place. `brain milestone suggest` never proposes a wave or an era. No era is
  created by the engine: an era is the owner's.
- **Projects the brain reads and never writes** (wi-brain-read-only-projects). A registry entry may say `access: read`
  (`write`, the default, is today's: the brain writes the project by PR; any other value is an error, « access is
  read or write », and the entry is not loaded until it is one). Such an entry holds `title` and `access` only, the
  shape of a tenant mount: `brain check --all` names every other key it holds (a root, a store, a ledger, a
  production list, repos...), each a way to write or read into it. `projects.load` never returns one, so sync, check,
  refresh, status, resume, audit, the queue, the cockpit and the guards (the registered repos, the production
  checkouts) pass it by; `projects.get` refuses it (« `<name>` is read only: the brain reads it and never writes
  it »), so does every `--project`; the neutral source refuses it as a rule file's `scope:` or a pack's `projects:`.
  `projects.readonly` lists them; `brain projects` (and `--json`, key `access`) shows them, `brain status --all` and
  the registry's check count them (« registry: 2 project(s), 2 store(s), ids unique; 2 read only »).
- **Projects that share a root** (wi-brain-shared-root-projects). The first project registered at a root owns it
  (`projects.for_root`, `classes.own_project` already read it so; now tested); each next one gets
  `Project.shares_root_with`, spans no repo by default (`repos_of`), and gets its stores' passes only: research_graph
  with its views beside its store and its own decision logs, its specs, its features' statuses, its module map. The
  root's own passes stay the owner's: the records and their view, the decision queue and the defaults, the rendered
  marketplace and AGENTS.md, the links graph and FEATURES.md, the public gate, the engine's skew, the session ids, the
  hygiene line (the queue keeps the owner's name, whichever project asks). Such a project declares its own stores,
  journal and decision log (the defaults are the owner's), none held by a project registered before it, its decision
  logs inside the root; until it does it is not loaded, and `brain check --all` and `--project` say why (fail
  closed: no command writes the owner's files through it; a file of any kind counts, a journal that is the owner's
  decision log too), while the guards and the usage governor keep protecting it (`projects.guarded`: its production
  checkouts stay refused to edits). An owner skipped for its access value (a typo, or `access: read` on an entry that
  still names its root) keeps its root and its files: the next project there stays a sharer and never becomes its
  owner, and `--store` naming the owner's store is refused with the reason (`projects._claimant`). A store whose
  views folder an earlier store at its root uses is refused by `brain sync` (`projects.view_clashes`) and by the
  checks, an owner skipped for its access value included (`projects.holders`). The permissions of a project that spans no repo are its
  root's settings, and its features' statuses come from the root's merged PRs. `brain audit --write` from it is
  refused: `notes/audit.md` is the owner's. Without `--all` or `--project`, `brain sync`, `check` and `refresh` at
  such a root cover every project registered there. Every store but a project's first at a root it owns gets
  research_graph's new `--views` (its parent folder: `ops/graph` writes `ops/kanban_graph.md`) and its decision logs
  (`--decisions`, the project's own from its first store, `--no-decisions` from another store): a project's second
  store no longer writes its board over the first's, nor derives its ADR stubs (an edge of it to one of them is
  named by `brain sync` and `brain check`). `--store` without `--project` runs as the project registered at the root
  that lists that store, with its layout and its passes only (`projects.lister`): the store of a project that shares
  the root never gets the owner's defaults. At a root one project holds, a store it does not list keeps
  research_graph's defaults, as before; at a root several share, `--store` without `--project` fails closed: the store
  of a project not loaded is refused with the reason, and a store none lists is refused too (never run as the owner
  with its defaults). Only `access: read` is read only (`projects.is_read_only`); any other value than read or write
  is invalid wherever the registry is read (`projects.bad_access`): `brain check --all`, `--project` and the neutral
  source's scopes and packs name it (« access is read or write, not 'maybe' »), and it is never loaded, listed or
  counted as read only. And `brain init` starts a template's later graphs beside their store, a later graph being
  known by its place in the template's graphs (also when the first one exists already and is kept). A project's
  `stores: []` holds its root's `notes/graph`, which sync and check run for it (`projects.stores_of`), and a store
  listed twice is refused by `brain check --all`. `brain audit --project` (and `--diff`) refuses a read-only, mounted
  or unloaded project with the reason `--project` gives (`projects.unloaded`). The module map's view sits beside its
  store's board the same way (`notes/modules_graph.md` for the first store, as before), and the resume pack names the
  project's own views. Nothing changes for a project's first store at a root it owns.
- **A scope's rules file may hold its front matter only** (`source/rules/scopes/<id>.md`: scope, title, intro), a
  scope with no rule of its own yet. It renders nothing and locks nothing: `lock:` in it is refused. A file outside
  `rules/scopes/` still needs a rule.
- The upgrade test (`compat-prev`) lays an `access: read` entry and a second project at the brain's root over the
  previous tag's brain, then rolls back over them (`tests/fixtures/formats/projects/v1/newer.yaml`).
- A conflict example in Markdown passes the marker guard and `brain check` when its fence is tagged
  `conflict-example` (`wi-brain-guards-fence-tag`, the owner's choice of 2026-11-10); every other fence is read as
  before, and a diff hunk that starts inside a fence whose opener it does not show is read as unfenced.
- `brain review prep [PR | BASE..HEAD]`, `brain review stamp HEAD` and `brain review check HEAD`: the review before
  the report, its zero-token part (`wi-brain-review-step`, `docs/review.md`). The packet holds the diff, the touched
  files at the head, `brain audit --diff`'s output and the lenses the touched surfaces call for (correctness always;
  security, compatibility, install and upgrade, procedure, tests, docs); the session's lens agents and two skeptics
  per distinct finding read it; the stamp, keyed by the head's full sha, records the counts for the error score and
  is what the merge gate checks.

### Fixes

- `brain adr new` no longer leaves an ADR appended without its edge. A layer file (`--edges-file`, `item add --file`)
  is `nodes/<name>.yaml` or `edges/<name>.yaml` relative to the store, checked before anything is written: the store's
  path given twice (`notes/graph/edges/rules.yaml`, which raised `FileNotFoundError` from `brain.notes.write` after
  the log was written) is refused and makes no folder, and a store with no `edges/` folder yet gets it. A root with
  no graph store is said before anything is written, and a file it cannot write is reported in one line.
- An engine error that only passes through `brain.nowindow`'s wrapper of `subprocess.Popen` is located at its caller
  (`selftime.where`): a child's missing cwd read `brain.nowindow:__init__`.
- `test_mergedriver.py::test_installer_step` expects the driver line of the brain the installer's Python imports
  under `-I`: on a machine whose venv holds a released brain, it no longer fails on every run.

### Changes

- The engine's CHANGELOGs are written from fragments (`wi-brain-changelog-unreleased-collisions`, the owner's choice
  of 2026-11-10): a PR adds `packages/brain/changes/<item>.md` (or `changes/<item>.md` for research-graph), a first
  line `section: Upgrade|Added|Fixes|Changes` then its entry, and never edits a CHANGELOG, so parallel PRs no longer
  collide in one `## Unreleased`. The version PR compiles them with `installer/changelog.py compile X.Y.Z --theme T
  --write`; `release-check` refuses a malformed fragment and a `## Unreleased` section on every PR, and a fragment
  left uncompiled on a version PR. The CHANGELOGs are `merge=brain` in `.gitattributes`, a net for a merge back from
  `release/X.Y` (`wi-brain-engine-changelog-driver`); a clone gets the driver with `brain merge-driver install
  --apply`.

## 0.2.8 — 2026-11-09 — the review fixes

### Upgrade

From 0.2.7, in this order. No schema, store or format changes, and no hand edit of a brain's data is needed.

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.

Nothing to run for the rest: `brain sync` (or the installer's `merge` step) rewrites the merge driver's line an
earlier engine wrote, keeping its launcher. The guards refuse more shapes of a third-party install or a piped download
(bash option clusters, launchers' options, Windows shims, corepack) and read `git add -A` and `git commit <path>` for
conflict markers and secrets: a command they now refuse says why.

### Fixes

- `brain.nowindow` also gives no window to a child whose `creationflags` is passed positionally or as `None` (the
  wrapper skipped the first and raised `TypeError` on the second); its review, which #70 never had.
- The session tree and the master's watch after the review of #34 (its medium and low findings):
  - a proposal card (`start_session` with `initiation` `offer` or `own_initiative`) and a call whose result is an
    error no longer make a session a master: a worker keeps its COST-1 checkpoint at 80 %; the app is asked at each
    check whether the owner started a session from the card, and a call that starts it by `proposal_id` counts
    (finding 22);
  - a budget state kept from before the master's watch asks the app at its next check, as meant (finding 53);
  - a subagent's tool call no longer uses up a step's notice: the main thread's next call gives it (finding 25);
  - an unarchived app child with a recorded SessionEnd stays live for the master's watch, its hand-over draft and the
    cockpit's Kids, as `brain sessions` reads it (`brain.sessions.alive`; finding 24);
  - `brain alerts` reads a master's liveness and live children from the session tree at each pass: an archived master
    or all of its children archived close the alert at once (one child of several archived keeps it, one live child
    fewer; a session the app does not know also ends with its recorded SessionEnd), a master waiting on its children
    for hours keeps it, and the state of a transcript the app's master has left (after a `/clear`) no longer raises it
    for up to 14 days (finding 26), assuming the app moves its file's `cliSessionId` to the new transcript after a
    `/clear` (not yet checked against a real one; were it kept, the earlier transcript's stale alert would stay and the
    current one would raise none, as the README says);
  - a session detached to the top level (`lineageDetached`) is no longer its old master's child, and a parent the
    app's file no longer names does not come back from the SessionStart event (finding 27), nor from the brief hash
    that `brain sessions`, `sessions tree` and `sessions show` read by default: the briefs give a parent only to a
    session the app does not know;
  - `brain check` refuses an unknown `local_` stamp only when it is under 7 days old; an older one is a warning (its
    session may have left the app and the ledger's two months), so a valid DDR no longer keeps the check red (finding
    23);
  - a `claude` started from a desktop session's shell no longer takes that session's app id in its SessionStart
    event, its session record, the master's watch, its DDR stamps or the resume pack's Session line
    (`brain.sessions.host_for`; finding 50);
  - a child's report takes its wait and recap from the wrap-up of its last turn only (finding 51), and the 80 %
    hand-over draft shows each child's state now, read from its transcript (finding 52);
  - `brain sessions tree` keeps `--hours` for sessions the app does not know (finding 55), and the options given
    before `tree` or `show` are no longer reset (finding 56).
- The merge driver after the review of #21 (`wi-brain-mergedriver-review-fixes`): a driver that cannot run (its
  launcher gone, an engine without it) no longer leaves ours alone with no conflict marker: its command falls back to
  `git merge-file` when it wrote nothing (exit 2 or more). An older config is rewritten with no step of yours:
  `brain sync` (which `brain update` runs) and the installer's `merge` step bring an earlier engine's line to this
  one, keeping its launcher, and leave a repo with no driver or another driver alone
  (`wi-brain-mergedriver-auto-apply`). A log entry both sides hold (a squash-merged or cherry-picked one, an add/add) is written once, not twice.
  The CHANGELOG union keeps a bullet both added once, with its continuation lines, and never drops a line of a
  released section.
- An exec event's end is never before its start (`wi-brain-selftime-end-before-start`): both come from one clock,
  the end clamped to the start; `datetime.now()` against a start rounded up across a millisecond put it 1 ms before,
  now and then, and the schema refused the event (a test failed on CI with `event.end: before start`).
- The third-party and conflict-marker guards after the review of #26 (`wi-brain-guards-kits-review-fixes`):
  - `guard.sh` starts Python for `claude` then `plugin`, or `skills` then `add`, whatever comes between: a quoted
    `claude.exe` (the desktop app's, by its full path), global options (`claude --model opus plugin ...`) and a line
    continuation no longer skip the guard.
  - Refused now: a here-string glued to its `<<<` (`bash <<<"$(curl ...)"`, `sh<<<...`), an unquoted `eval $(curl
    ...)` or `sh -c $(curl ...)`, a shell, `source`, `.` or python reading the download through `/dev/stdin` or
    `/dev/fd/0` (`curl ... | bash /dev/stdin`, `source /dev/stdin <<< "$(curl ...)"`), `curl ... | python3 -E`.
  - `claude plugin`: global options before `plugin` and the values of `--config`, `--scope`, `--marketplace`,
    `--sparse a b` no longer shift the plugin or source checked; every operand is checked, and `plugin install
    --marketplace SOURCE` is checked as a source. `skills add` through `bun x` and after a launcher's global option
    (`pnpm --silent dlx`, `npm --yes exec`) is refused; `skills add REPO --list` and `-h` pass.
  - Pass now: a process substitution a named script reads as data (`python3 analyze.py <(curl ...)`, `bash
    ./compare.sh <(curl ...)`), and `curl ... | python -I parse.py` (python's `-I` takes no value).
  - Markers: a merge's resolution commits over content the merged branch already holds (a line counts only when new
    against every parent); `git add -A`, `-u` or `-p` with no path read the whole worktree from a subfolder, `:/` and
    exclusions are read as pathspecs, and `-u`/`-p` read no untracked file; `git commit PATH` (`--only`, `-i`) reads
    PATH's working tree (the secrets and public checks too); a pure `git mv` adds no line; a path with a space (git's
    TAB) or C-quoted keeps its setext heading; `.qmd`, `.Rmd` and `.txt` headings pass; only the files whose changes
    hold a marker-like line are read (`git diff -G`), an untracked file is read whole, and a diff git cannot show
    whole is an error in `errors.log`, never a silent pass.
  - After the review of #79: a commit in a folder that is no git worktree when the guard runs (missing, or its `git
    init` later in the call, git's "not a git repository") passes with no `errors.log` entry, as on main, while
    any other failure of that check (git missing from PATH, a timeout, dubious ownership) is a logged error; a
    `.txt` heading passes only under a title no longer than its underline (reST's rule), so a bare `=======` left
    in `requirements.txt` is still refused; bash's option values are no script (`curl ... | bash -o pipefail
    /dev/stdin`, `| bash -o pipefail`, `| bash -O extglob`, `| bash -eo pipefail`, and an `o` or `O` anywhere in a
    cluster, one value each: `| bash -oe pipefail`, `| bash -Ox extglob`, refused; a script's own `-s` no longer
    reads as bash's); a launcher's global option with a value is skipped before its verb (`npm -w pkg exec`, `npm
    --loglevel silent exec`); npm's Windows shims `claude.cmd`, `claude.ps1` and `skills.cmd` are claude and skills,
    and the launchers' own (`npx.cmd`, `pnpm.cmd`, `npx.ps1`, `bunx.cmd`) unwrap too: `npx.cmd skills add` and
    `pnpm.cmd dlx skills add` are refused (`_prog` reads a shim of a launcher, claude or skills; another script keeps
    its name).
  - After the second skeptic round of #79: every check reads `bash -c`'s command past the options' values too, as
    bash does (`bash -euo pipefail -c '...'`, `bash -co pipefail '...'`, `bash --rcfile FILE -c '...'`, `bash -c --
    '...'`): `bash -euo pipefail -c 'curl ... | sh'`, `... -c 'npx skills add ...'` and a production write behind
    `-euo pipefail` were not seen. `corepack` is a launcher: `corepack pnpm dlx skills add`, `corepack pnpm@9.12.0
    dlx ...`, `corepack yarn dlx ...` and `corepack npx skills add` are refused; corepack's own verbs (`enable`,
    `install`, `up`) run nothing.
- **The answers' lane, the rest of the review of #19** (wi-brain-answers-fixes). `brain record ddr` applies the
  one-writer rule to an answer it writes (`--id ID --answer/--other`, or a `--file` that adds or changes one): in an
  agent's session only an answer its own question tool captured (finding 9). `brain decision defaulted --apply` and
  `--seen` no longer write a main checkout on main or master unless `--on-main`, as `brain refresh` (finding 32).
  `--all --seen ID...` takes full ids, each marked in the one project that holds it, every --seen id found and
  checked in every project before any is marked (with `--apply`, the defaults due are taken first and stay taken when
  an id is refused); the queue views are rewritten even when a check refuses (finding 33). `brain refresh` and
  `brain sync` take the low-stakes defaults due before they write the records' graph and the kanban, which showed
  those DDRs pending until the next refresh (finding 35); when a later step of the sync fails, the queue view is
  rewritten all the same, so it never shows a DDR pending that the records hold answered by default. `--captured`
  prints the captures it retired (« retired, never recorded », with each reason; `--dry-run` marks the refused ones)
  apart from the decisions left because they are no longer pending, the only ones `--again` replaces.

### Changes

- A written version policy (`docs/release.md`, « The version policy », wi-brain-versioning-policy): before 1.0 the
  middle number moves for a change an owner must act on or a format that moves, the last for what needs nothing; each
  release has a theme; a fix that cannot wait is a patch cut from the last tag; a release a week, the review fixes on
  it. CI's `release-check` now refuses a patch whose registered schemas changed since the last tag or whose
  `### Upgrade` numbers a step beyond the three standard ones (by their bold titles: **Install the engine**,
  **Restart the Claude Code sessions**, **Refresh the public stamp**), any version whose `### Upgrade` leaves
  out one of these three (a version PR's section numbers them, so `brain update` prints them), a brain section heading with no theme
  (`## X.Y.Z — YYYY-MM-DD — theme`; punctuation alone after the date, `## 0.3.0 (2026-11-16)`, is none), and a section of either CHANGELOG that repeats an entry an earlier section
  released (a fix that cannot wait, left in main's `## Unreleased` when `release/X.Y` merged back; by its text, a
  « No change » line and the `### Upgrade` steps aside). It writes its messages in UTF-8
  to a pipe. Every release up to 0.2.7 predates the policy, and 0.2.7 is the last.

## 0.2.7 — 2026-11-09

### Upgrade

From 0.2.6, in this order. No schema, store or hook changes, and no hand edit of a brain's data is needed.

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart Claude Code's sessions**, so that they run the hooks `brain sync` rendered.
3. **In each public repo's checkout**, run `brain check --public --history` before the next push: a stamp is valid only
   under the engine that made it, so the push guard refuses the old one until then.
4. **Read this if a script of yours runs `brain --project P` from a linked worktree of P's repo:** it now acts on that
   worktree, not on the registry's root. Pass `--root` to choose another.

Nothing to do for the rest: a scheduled task opens no window for its children from its next run, with no reinstall;
`days` and `quiet_hours` are optional; quiet mode creates its two files in `<BRAIN_HOME>/notify` when first used.
Optional: declare `usage.plans` in `config.json` so that `brain usage quota` knows the plan in force; until a plan has 3
converted readings it reports `uncalibrated`.

### Fixes

- A scheduled brain opens no window for its children (`brain.nowindow`): under `pythonw.exe` every `git` or `gh` of an
  alerts pass got a console of its own, in Windows Terminal where it is the default terminal, and took the focus,
  dozens of times per pass. A brain with no console now starts each child with `CREATE_NO_WINDOW`.
- `brain status` reads the quota's clock from `usage.now_utc`, like the rest of the quota: a test that froze that clock
  saw the real time in the status row, and failed on every commit once its fixed reset (2026-11-09 12:00 UTC) had passed.
- `brain <cmd> --help` no longer crashes without a stdout (pythonw.exe, Python 3.10: argparse wrote to None); it
  survives a cp1252 pipe too, the CLI already writing UTF-8 with `errors=replace` (`wi-brain-help-encoding`).

### Changes

- `brain usage quota` converts dollars to percent with the readings of the plan in force only
  (wi-brain-quota-per-plan; config.json `usage.plans`, a reading's own `plan` first): a median across an Ultra and a
  Pro week was neither plan's quota. Until the plan has 3 converted readings (`quota.CAL_MIN`) the conversion is
  reported `uncalibrated` (in the text, the JSON's `uncalibrated` and the `brain status` line), the weekly window is
  not converted, and the 5-hour window is estimated from its latest reading plus the ledger's cost since
  (`window_5h`). The weekly reset is still read from every reading: it is the account's.
- `brain --project P` run from a linked git worktree of P's repo acts on that worktree, not on the registry's root
  (wi-brain-root-from-cwd). An explicit `--root` still wins; a cwd in another repo or a plain folder keeps the
  registry's root.

### Added

- `schedules:` entries take `days` (mon to sun), the days `at` runs on, so that a weekly command can be declared and
  installed like any other (`days: [mon]`): a `ScheduleByWeek` trigger on Windows, `OnCalendar=Mon ...` under systemd,
  the day-of-week field in a crontab. A task whose days changed is planned as an update (wi-brain-schedule-hidden-all).
- **Quiet mode** (wi-brain-quiet-mode): `brain quiet --for 2h` or a project's `notify: quiet_hours: "22:00-07:00"`
  (local time) holds every notification below `critical`; a critical one still goes through. The held ones are summed
  up in one message per project when the quiet ends (`brain quiet --off`, or the next alerts pass). No task is
  paused and no scheduled task is touched: collection and the alerts pass run on. The state is in `brain quiet`,
  `brain status` and the cockpit's health card. A send during a quiet reports `held` (`brain notify send` exit 0).

## 0.2.6 — 2026-11-09

### Upgrade

From 0.2.5, in this order. No hand edit of a brain's data is needed: the upgrade test (`compat-prev`,
`docs/release.md`) installs this engine over a brain 0.2.5 wrote, moves the pin and runs `brain sync`, `brain check`
and `brain record check`.

1. **Check the configuration first**, with 0.2.5 still installed: `brain config --check` and `brain config` (its `file`
   and `personal`). The public and secrets checks now fail closed (wi-brain-guards-fail-closed, COMPAT-4): from
   the install on, every `git commit` and `git push` is refused on a machine whose `config.json` is unreadable or not
   an object, has a `public` (or one of its keys) of another type or a `v` above 1, whose `$BRAIN_CONFIG` names no
   file, or whose `personal.json` names a folder without `config.json` (a renamed personal brain); so too when the
   hooks find no Python that imports brain. An unknown key never refuses. The override is
   `BRAIN_GUARD_ALLOW=public:config`.
2. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. 0.2.5 runs
   this update and only reminds you of the pin. A brain whose `config.json` declares `engine.installer`: merge the PR
   that moves `engine.pin`, then run the installer's `-Apply` instead.
3. **Move the pin and render the hooks.** Run `brain update` again and answer `y`: 0.2.6 now does what 0.2.5 left to
   you (wi-brain-update-moves-pin, COMPAT-5): it writes `engine.pin`, commits `config.json` alone (never pushed) and
   runs `brain sync`, which rewrites `guard.sh` and `health.sh`. With changes in `config.json` not committed, it leaves
   the pin and says so. A brain that declares its installer: run `brain sync` after `-Apply`; its pin never moves
   except by the reviewed PR.
4. **Restart the Claude Code sessions**, so that no older bash hook from the plugin cache keeps running.
5. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push (wi-brain-public-stamp-binding). A stamp written by brain 0.2.5 or older has no key, and the push guard
   refuses it, as it refuses any stamp made under another engine, other public rules or with gitleaks gained or lost.
   So this step comes back after every engine upgrade.

Nothing to run for these:

- **The cockpit's number keys now go to tabs** (wi-brain-tui-layout). Nothing to run: 1 is the queue, 2 the sessions, 3
  the frontier, 4 the milestones, 8 health and 0 the overview, where 1 to 8 used to focus a panel of the grid. `m` is
  offered only where a tab shows several panels, and Escape goes back one step at a time: the search, a full view, then
  the overview. `tui.json` gains `tab` and `tabs`;
  an older engine ignores them and forgets them at its next save.

- Nothing to run for the machine-local state (wi-brain-state-safe-io). `vault/state.json` gains `"v": 1` at its
  next write, which brain 0.2.5 reads unchanged; `schedules/installed.json` and `alerts/state.json` keep their v 1
  unwritten. Each of the four files may now have a `<name>.bak` beside it, and a file that was unreadable a
  `<name>.unreadable-<stamp>`: both are safe to delete once you have looked.

- Nothing to run. Outside CI, a check that used to fail on an unknown key in `config.json`, `permissions.yaml`,
  `packs.yaml`, `projects.yaml` or a record now prints a note instead; CI (`CI` set) still fails on it. A `v` above 1
  in `config.json`, `permissions.yaml` or a record was refused before and is still refused, now with « brain
  update »; `packs.yaml`'s `v`, written but never read until now, is refused the same way.

### Changes

- **The release checklist** (wi-brain-release-checklist; spec-brain-data-compat, gate item 6). `docs/release.md` says
  every step of a release, from the version PR to the pin. CI's new `release-check` job (`installer/release_check.py`,
  standard library only) reads the last tag on every pull request. On a version PR, it fails when a registered schema
  changed since that tag and this version's CHANGELOG section has no `### Upgrade` with something in it, and when
  the two `__version__`, the research-graph pin, the hooks' `brain_version` and both CHANGELOGs' dated sections do not
  agree: what `release-tag` used to find out only after the tag. Any other pull request passes it at once. An Unreleased
  section now keeps its `### Upgrade` apart from its `### Changes`.

- **The cockpit's tabs** (wi-brain-tui-layout, UX-2, UX-18; spec 2026-11-03 cockpit-ux-round2 §4.0). One tab per
  question, in data (`cockpit.TABS`: key, label in English and French, question, views and their panels, count): 0
  overview, 1 queue, 2 sessions, 3 frontier, 4 milestones, 8 health (alerts on top;
  audit debt, stacks and index, and a new frame of exec times with the slowest steps). Ideas (5), lessons (6), features
  (7), resources (9) and settings (the comma) arrive with their items, and until then their key says so. The bar shows
  each tab's state in digits and signs (the queue's band now, the sessions asking `!`, the open alerts), a click on it,
  ctrl+pageup and ctrl+pagedown change tab, and its tooltips name each tab with its key and question. Under 120 columns or 30 rows the bar is reduced to its
  numbers, the active tab named, the grid is not offered and the health frames stack. A tab keeps its panels' cursor and
  scroll: they are the same widgets, laid out again. `v` or a click in the toolbar changes the view; the toolbar says
  the tab's question and holds an `[i]`; the global bar says the last change and the next probe. The last tab and each
  tab's view are kept in `tui.json`. `brain tui --tab NAME` starts there, and with `--once` or `--plain` prints that
  tab's panels alone.

- **The cockpit's column chooser and palette** (wi-brain-tui-layout; spec cockpit-ux §4.4). `C` chooses a table's columns
  (`cockpit.columns`, `brain.tui_palette`): shown or hidden, their order, and the longest its title may be, the rest in
  the detail; the sessions also offer Cost, App id, Id and Branch (`EXTRA_COLUMNS`), the Cost column sorting by cost. They
  are kept in `tui.json`'s `columns`, which an older engine ignores and forgets at its next save. A state's colour follows its word wherever it is
  placed. The palette (`ctrl+p`, `cockpit.palette`) gains an entry for each tab and view, project, sort, filter and table's
  columns, and « Reset the views », which keeps the project, the theme and the timezone.

- **The cockpit's detail beside the list** (wi-brain-tui-layout, UX-20; spec cockpit-ux-round2 §4.0.2). From 140 columns,
  on a tab that is one list (`cockpit.detail_beside`), a row's detail sits right of the list and follows the cursor
  (`brain.tui_side`): it is read once the cursor rests, in a worker thread, and remembered per row until its panel changes,
  so an arrow held down reads nothing. Enter gives it the focus, Escape gives it back, `o` opens a link from it, and `a`, `d`
  and `A` work from the list too, after the same confirmation. Narrower, or on a tab of several panels, Enter opens it
  over them as before.

- **The cockpit's overview: one card per tab** (wi-brain-tui-layout, UX-19; spec cockpit-ux-round2 §4.0.3). The overview
  opens on its cards (`cockpit.cards`, each tab declaring its own): the queue's band now, the sessions asking, the nearest
  milestones, what can start, the open alerts, worst first across the projects, and the audit. Enter or a click opens
  the tab, already filtered as the card says, its search cleared, by a filter that is never saved and goes when the tab
  is left (the filters dialog makes it the owner's); the arrows move between them, and they take one column on a narrow terminal. The grid and the digest are its other views
  (`v`). `brain tui --once --tab overview` prints the cards. In the digest view the frame no longer repeats its title on
  each project and above the digest (L9); in the grid, open alerts take a whole row (L11). A key now moves the focus at
  once, so `1` then Enter opens the queue's row, not the previous tab's. A table's cell is text, never markup: a title
  like « Move [/docs] out » crashed the cockpit, and « [blocking] » vanished from the queue's Id column.

- **A public-check stamp is valid only under the key it was made with** (wi-brain-public-stamp-binding,
  spec-brain-data-compat N2 and finding 11; `docs/formats.md`, « Public-check stamps »). The stamp of a green `brain
  check --public --history` now carries `v` 2 and a `key`: the engine version, the sha256 of config.json's public
  deny, allow, patterns and refuse, and whether gitleaks read the history. The push guard refuses a stamp whose key
  differs from now's (another engine, rules changed since, gitleaks gained or lost), an old-format or unreadable one,
  naming why and the fix, « rerun brain check --public --history ». A check with no commit to read keys gitleaks by
  its presence on the PATH; a gitleaks on the PATH that fails stamps nothing (exit 1, « fix gitleaks or take it off
  the PATH »), since the guard would refuse that stamp; a stamp is written atomically; a newer brain's stamp, a
  nested or unreadable one, or any surprise while reading it refuses the push instead of letting it through.

- **`brain update` moves the pin where no review step exists** (wi-brain-update-moves-pin, spec-brain-data-compat
  COMPAT-5). For a brain whose `config.json` declares no `engine.installer` (one from `brain init`), the plan's last
  steps write the new tag into `engine.pin` (the file's other keys, their order and its indent kept; written
  atomically), commit `config.json` alone (« brain update: engine.pin vX -> vY »), then run `brain sync` with the new
  engine, on the owner's `y` or `--yes`. With the latest engine already in the brain's venv and the pin behind it, the
  plan moves the pin alone. The pin never moves backwards, nor to or from a pin that is not a release tag, nor for an
  editable install; a `config.json` with changes not committed or not tracked, or a brain that is not a git repo or
  is on a detached HEAD, is left as it is (exit 1, with what to do by hand); the commit lands on the current branch,
  never pushed. From a Claude Code session the command refuses, as before, and says to run it in
  the owner's terminal. A brain that declares its installer keeps the reviewed pin PR, shown and never done. The plan's
  `--json` gains `pin.move` (`"write"` or `"pr"`).

- **The cockpit's empty, error and offline states** (wi-brain-tui-states; spec 2026-11-02 cockpit-ux §4.10). An
  empty table shows one line that says why (`cockpit.why_empty`): a filter or the search hides N rows, and the key
  that changes it; nothing in the scope, the owner named; a project not on this machine. A panel not probed yet shows
  the probe's countdown, then its progress project by project (`probe_wait`). `Cockpit.refresh` no longer raises: a
  failed read keeps its panels' content, its error and the data's time go to the snapshot (`errors`, `panel_at`) and
  the panel's frame, the TUI notifies it once, and it is read again at the next tick, a probed panel at the next
  probe (before, a failed graph read waited for the next file change). `--once` and `--json` print a failed read on
  stderr and exit 1 (they used to raise); `--detail` names it when it finds no row. A stack or code index repo not OK
  names its last OK measure. The project selector greys a registered project this machine lacks; `brain tui --all` without a
  registry shows the folder's project instead of exiting. `brain tui --json` gains `errors`, `panel_at`, `probing`
  and `registry`.

- **The cockpit's queue sorts by score** (wi-brain-tui-queue-sort-score). The queue panel's `score` sort ranks by
  the score alone, across the bands: the highest first (an entry without a score last), then what it unblocks, then
  the oldest. It is the second sort of `s`, a click on the Score column, `brain tui --sort queue:score`, and a view
  `tui.json` remembers (a saved sort a panel does not know still falls back to its default). The default stays by
  band, the owner's order, then the score. `brain tui --help` now lists every panel's sorts from the code.

- **Machine-local state is never reset and saved over** (wi-brain-state-safe-io, spec-brain-data-compat N4;
  `docs/formats.md`, « Machine-local state »). `brain.stateio` loads and saves a truth-local file: a file that is not
  JSON, not an object or not its expected shape is set aside as `<name>.unreadable-<stamp>`, never replaced by `{}`
  and saved; a `v` above the engine's makes it read-only (« written by a newer brain: brain update »); every write
  backs up to `<name>.bak` beside the file (a secret is never copied), then writes atomically, synced. It now carries
  `schedules/installed.json` (`brain schedule install --apply` refuses a newer record), `alerts/state.json` (the
  notify pass sends nothing rather than send again each pass), `vault/state.json` (gains a `v`; a non-object no
  longer crashes `brain vault`; `seal`, `canary` and `drill` refuse a newer state before any work; the one-way drill
  migration backs up first) and `usage/sessions.json` (a newer ledger is updated in memory, never saved). The 17
  `return {}` readers are classified in the same page; the rest of the truth-local ones follow. Only a command that
  writes a file sets it aside (`brain status` and the cockpit move nothing); `brain vault reseal --apply` refuses a
  newer state before resealing; a backup that fails (a locked `.bak`) is said and the write goes on.

- **The upgrade test, on every pull request** (wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and
  COMPAT-3). `installer/stranger_test.py --upgrade-from TAG|DIR`: the tag writes every registered format into a new
  brain (a decision, an AR, an SR, `permissions.yaml`, its exec events; a format with fixtures and no place in the
  test fails it), then this engine is installed over it and runs strict: the store plan, `brain sync`, `brain check`,
  `brain record check` and the Lite scenario. Then the rollback: the `newer` fixtures' additive keys laid over the
  brain, a canary and a drill on record, the tag installed back, and its check, record check, permissions check,
  vault status (the drill shown), `brain perf` and a newer template's plan run in read mode; a tag with the read mode
  must pass them, 0.2.5 may only refuse the newer keys. Then this engine again makes the same reads, all passing. No
  file of the brain or of the vault may change and the ledgers may only grow, over the whole round trip; after each
  install, `direct_url.json` must name the engine meant. CI's new `compat-prev` job (Windows, pull requests) runs it
  from the last tag (none found fails it) and uploads its report. The stranger test's exit code is 1, not 2, when a
  step fails after a good first install. `docs/formats.md`.
- **The public and secrets checks fail closed** (wi-brain-guards-fail-closed, COMPAT-4; the 2026-11-04 REVERSAL of
  the guards' internal-error policy, for these checks only). A new check, `public:config`, refuses every `git commit`
  and `git push` while `brain.config.unexpected` finds the configuration unexpected: `config.json` unreadable or not
  an object, `public` or one of its keys (`repos`, `deny`, `allow`, `patterns`, `refuse`) of another type, a `v` that
  is not a whole number or is above the engine's, `$BRAIN_CONFIG` naming no file, or no `config.json` found although `$BRAIN_PERSONAL` or `personal.json` names a personal brain. An unknown key never refuses. Each
  reason names its fix (`brain config --check`, `brain update`, `install.ps1 -Apply`). `guard.sh` refuses a shell
  command naming git and commit or push when it finds no Python, or the one it finds cannot import brain (« the
  guards cannot run »); before, it let every call through in silence. The SessionStart health says both (`health.py`
  through `brain.stacks.hook_main`, `health.sh` when no Python can run it). `BRAIN_GUARD_ALLOW=public:config` lifts
  the Python check. `config.json` is now read with or without a UTF-8 BOM (Windows PowerShell 5.1 writes one), as
  the installer reads it. `health.sh` now tries guard.sh's interpreters in guard.sh's order (`$BRAIN_PYTHON` first),
  so what it says of the guards is what they run on. `docs/guards.md`.
- **Remote Control's three exceptions** (wi-brain-guard-rc-archive; the owner's ADRs of 2026-11-04). The
  session-settings guard lets the desktop app's `set_remote_control` through in exactly three cases, each checked
  from the app's own session files and the hand-over notes: off on a finished (idle) session the caller started,
  before archiving it; at a handover between Brain coordinators, on for the coordinator the caller started to succeed
  it, and off on the caller itself once that successor is detached, both once the caller's hand-over note (a `*.md`
  in `<BRAIN_HOME>/handover/` whose first app id is the caller's, under 6 h old) exists. A coordinator is marked by
  the name its starter gave it (`coordinator-g`), never by its title, and must itself have been started by one. Each
  pass is logged in the guards ledger (`"decision": "allowed"`, its `case`), and a pass the ledger cannot take is
  refused; anything the guard cannot read is a refusal, and an error in the guard now refuses a session-settings call
  instead of letting it through. `set_session_permission_mode` and the app's settings stay refused, and
  `BRAIN_GUARD_ALLOW` still lifts nothing. `brain.sessions` reads the app's `lineageDetached` (`detached`). Acts once
  the engine is installed (`install.ps1 -Apply`). `docs/guards.md`.
- **Tolerant readers, strict writers** (wi-brain-tolerant-reader, COMPAT-1's gate; `docs/formats.md`). The schema
  validator gains two modes. Read mode keeps a field it does not know (a newer brain's additive one) and reports it;
  strict mode, for every write and for the checks in CI (`CI` set, or `BRAIN_STRICT=1`), refuses it. A `v` above the
  engine's is refused in both: « `<file>`: v2 is written by brain > 0.2.5, which reads v1: brain update ». It covers
  the five schemas (DDR, SR, AR, event, config.json), `permissions.yaml` (an allow rule with an unknown key is left
  out in read mode, since the key may narrow it), `packs.yaml`, the template manifest (its `engine:` range is checked
  before its keys, so a newer template says « it needs brain >=X ») and `projects.yaml` (`KEYS`, `REPO_KEYS`). A DDR
  or SR rewrite, even one rebuilt afresh (`--replace`, `brain record backfill --update`), puts back the unknown fields
  of the file it replaces and never replaces one a newer brain wrote (backfill counts it `sr-refused`). AR lines
  are parsed one by one: a broken line is an error of `brain record check`, a newer brain's line (a higher `v`, an
  unknown kind) is skipped and counted, and neither stops `brain sync`. Fixtures under `tests/fixtures/formats/`: an
  older and a newer file per format, round-tripped without loss.
- **The validator enforces `maximum`** (wi-brain-schema-keywords). `config.json` `usage.guard` `critical: 950` no
  longer passes and silently turns the governor's refusal off. `brain.schema` refuses a schema that uses a keyword it
  does not implement (or `if`/`then` outside an `allOf` entry of their own, `items` as a list), and a test fails on
  one.
- **The answers' lane on the question tool's real shapes** (wi-brain-capture-multiselect,
  wi-brain-capture-unanswered). The tool returns a multiple choice as a list of labels: the capture of an ad-hoc
  question raised a TypeError and the whole tool call was lost (`ledger/errors.log`). `capture.ddr_from_question` and
  `answers.capture` take the list (or the labels joined by `, `). When the owner sends a message instead of answering,
  the tool returns a placeholder for each question (« [User did not answer this question — they sent a message
  instead. …] »): it was captured as the owner's free text. It is now no answer: nothing is captured for a printed
  question, an ad-hoc DDR stays pending, and `brain decision answer --captured` refuses, lists and retires the rows an
  older engine wrote, `--again` included. A test fixture holds both tool results, copied from real transcripts and
  redacted.
- **The answers' lane, review of #19** (wi-brain-answers-fixes). `--captured` retires what it does not write (a new
  `retired` reason in `answer-recorded`, with each capture's `captured_at`): an older capture of a DDR whose later one
  was recorded never comes back; a capture older than the answer the DDR holds is stale, never written, `--again`
  included. An answer captured before a low-stakes deadline wins: `brain refresh` leaves such a DDR pending, and
  `--captured` replaces a default another branch took meanwhile. A label the session shortened in the tool is kept
  `unmapped` and refused, never recorded as free text. The header-and-labels match looks only at the questions this
  session's batch printed (the asked ledger now records the session). The recorded ledger is read from the month of
  the oldest capture on. The never-by-default check reads amounts with a currency sign (`40€`, `$50`), `-`/`_`
  compounds (`ssh-key`, `API_KEY`, `cron-job`), more synonyms and forms (cost, spend, sign-in, Task Scheduler,
  PyPI, settings.json, a GitHub PAT, `.env`, rotating keys), the recommendation's why and the linked ids; `brain
  check` applies it to pending DDRs only, so a word learned later never fails a decision already answered. A typed
  single-choice answer that starts with a label (« No, because… ») stays the owner's text in an ad-hoc DDR, and a
  joined multiple choice takes the longest label. The review list shows a low-stakes DDR answered in time through
  the question tool as such, not « due now ». A stamp without a zone is UTC instead of a TypeError
  in refresh, the batch and the cockpit. `reversed` is a non-default answer after the deadline (compared as times),
  never one that took the default's option, and `--seen` clears it; `--seen` checks every id before it writes.
  Left for after the command registry (they need `cli.py`): `brain record ddr --answer` without the one-writer
  check, `defaulted --apply` writing main checkouts, `--all --seen ID`, the refresh that writes the records graph
  before taking a default, and printing the refused captures apart from the skipped ones.

- **Git's identity before the first commit** (wi-brain-install-git-identity). A fresh Git for Windows has no
  `user.name` nor `user.email`, and the first commit of `docs/install.md` stopped at « Author identity unknown ».
  `brain init --apply` now asks git, as a commit would (`git var GIT_AUTHOR_IDENT` and `GIT_COMMITTER_IDENT`, from
  the new brain's folder), whether it has an identity; when it has none, its next steps add the `git config --global`
  commands for the keys git's config lacks (the owner's name for a person, a placeholder for a team or a name a shell
  would expand: `$`, a backtick, a backslash, a quote). Nothing is printed when the commit would pass (the config, the
  `GIT_AUTHOR_*` variables, git's own guess) or git is not found. `docs/install.md` (step 3,
  Windows and Linux) and `docs/pilot.md` set the identity before the first commit.
- **The onboarding at the installed tag** (wi-brain-onboarding-tag-links). The vault runbook that `brain init` and
  `brain vault status` print points to `blob/v<the running version>`, not `blob/main`, which may be ahead of the
  engine installed. `docs/install.md` and `docs/pilot.md` say to read them at the tag installed, and now explain the
  vault that `brain init` names: data classes (`brain classes`), optional in the pilot (`vault OFF` until it is set
  up), the runbook for when it is wanted.
- **A command registry** (wi-brain-cli-registry). Each top-level command is now a module of `brain.commands`
  (`src/brain/commands/<name>.py`): its parser (`register(sub, ctx)`), its handlers (`run(args, root)`, and
  `early(args)` for what runs before a root is resolved), its place in `brain --help` (`ORDER`) and its usage lines
  (`USAGE`, `USAGE_ORDER`). `brain.cli` keeps `main` and `build_parser` as a facade: it lists the package, adds each
  module's parser and dispatches to the module, and it no longer holds an `add_parser` call. A new command is a new
  file; the README's « Adding a command » shows one. Nothing a command does or prints changed: `tests/help_dump.py`
  prints the help and the arguments of every command and subcommand (149 parsers), byte for byte the same before and
  after the move.
  - `brain audit`'s new check `cmd.registry` (ruleset 5; P1 on a production path, NEW and LEFT in the scout) flags a
    parser the `cli.py` beside a `commands/` package that lists its modules adds itself, and a module of that package
    with no `register`.
  - The inventory reads `pkgutil.iter_modules(__path__)` in a package's `__init__.py` as an import of each of its
    modules, so the audit's production closure and the tests' reach go through the registry as through an import.
  - The distribution's packages are `brain` and `brain.commands` (`pyproject.toml`): a wheel carries the registry.

## 0.2.5 — 2026-11-04

### Upgrade

From 0.2.4, in a brain that 0.2.4 (or older) initialised, in this order:

1. Move `config.json` `engine.pin` to `v0.2.5` and commit it: until then `brain sync` refuses another engine than the
   pin (the engine-skew refusal since 0.2.4).
2. Run `brain sync`: it rewrites the plugin's `guard.sh`, `health.sh` and `hooks.json`; until then `brain check`
   exits 1.
3. Add the `Lesson` node type to `notes/graph/schema.yaml` by hand, as `docs/lessons.md` shows: `brain lesson add`
   refuses until then, and the close-item retro is skipped with one line meanwhile.
4. Add `notes/modules_graph.md merge=brain` to `.gitattributes`, and the generated `notes/modules_graph.md` to
   `boundary.yaml`, by hand: `brain init` keeps the files it made earlier.
5. Restart the Claude Code sessions, so that no older bash hook from the plugin cache keeps running.

- **The four high findings of the review of the PRs merged without one** (wi-brain-fix-merged-highs).
  - `brain sessions`, the Stop snapshot, the master's watch, the cockpit and `brain check` no longer raise
    `TypeError` on a family that mixes an app child (its `createdAt`, milliseconds) with a ledger-only one (its
    SessionStart, ISO: its app file deleted, or half-written while the app rewrites it): the children sort on one
    start time in seconds (#34).
  - The third-party guard refuses a pipe continued on the next line (`curl URL |` then `sh`, `irm URL |` then
    `iex`): a newline right after `|`, `&&`, `||` or `;` keeps the operator's link (#26).
  - It refuses `iex "& { $(irm URL) }"`, `iex "$(irm URL)"` and `Invoke-Expression "..."` alike, directly or through
    `powershell -c`: PowerShell expands the string's `$( )` before `iex` runs it (#26).
  - `brain decision answer --captured` finds each DDR by its exact id on the default branch: one asked on a branch
    not merged yet is left captured and said (« not on the default branch yet »), the batch's other answers are
    recorded, and a DDR whose id merely contains the captured one is no longer answered in its place
    (`decisions.find(..., exact=True)`; #19).
- **Coverage in the CI** (wi-brain-test-coverage). The `brain` job on Windows, Python 3.12, runs the suite from
  `packages/brain` with `--cov=src --cov-context=test` and keeps the data file as the artifact `coverage-data`, which
  `brain coverage --from coverage.data --cwd packages/brain` reads (`relative_files = true` in packages/brain's
  pyproject.toml; `pytest-cov` joins the test extras). It never fails on a threshold. Docs: `docs/tests-graph.md`.

- **The schedules** (wi-brain-alerts-pass). The registry's new `schedules:` key, `{name: {command, every, at,
  at_logon, machines, timeout, enabled}}`, declares the brain commands a machine's scheduler runs, the alerts pass
  every 15 minutes and at logon first. New `brain schedule install [--apply] [--json]` (`brain.schedule`): the plan,
  then the Task Scheduler (`\Brain\<name>`, the user's interactive token, the venv's `pythonw.exe`, IgnoreNew,
  StartWhenAvailable), a systemd user timer or the user's crontab, through `bash -lc`; what this machine installed
  and no longer declares is removed (`<BRAIN_HOME>/schedules/installed.json`), a task registered by hand never.
  `brain schedule list`. The installer's new schedule step runs it (a plan line, applied by `-Apply`); `brain check
  --all` checks the entries, refusing a control character or an unbalanced quote in a command. `--apply` is refused
  from a Claude Code session, and the guards refuse `brain schedule install --apply` (owner, scheduled). A task
  already deleted by hand is removed without an error; a schedule recorded under another scheduler than this run's
  is left alone with a note; the Task Scheduler's XML is read in the OEM code page and compared with its entities
  decoded.
- **The alerts pass's dead-man** (wi-brain-alerts-pass). Each `brain alerts --notify` pass records itself (`_pass`
  in the state: when, where, the unset variables); once the pass is installed here, `brain schedule list`, `brain
  status`'s alerts row and the SessionStart health hook say SILENT when its last run (or its install, the later)
  is older than two cadences of the machine's awake time, so a boot or a wake raises no false SILENT.
  Without its channel's variable (an unset `BRAIN_NTFY_TOPIC`) a pass sends nothing, writes no notify audit line and
  says so in one line; those alerts go at the first pass that finds it. Off Windows the alerts' Task Scheduler
  folders are skipped instead of raising a `scheduler` warning.
- **Linux** (wi-brain-install-linux). The installer ran under `pwsh` 7.6 on Ubuntu 24.04 (a container): the venv, the
  `~/.local/bin` link, `brain init`, the personal brain's setup (pointer, merge driver, Lite profile, permissions), the
  Claude Code plugin, the hooks under bash and the guards on Linux paths; `docs/install.md` gains its Linux section
  from that run.
- **Tests linked by their imports, and coverage measured** (wi-brain-test-links-auto, wi-brain-test-coverage;
  TEST-1). `brain sync`'s `tested_by` edges now also go to every Python test that imports a node's module itself,
  besides brain audit's strongest evidence; a CodeRef of a symbol (`path::name`) keeps only its file's tests that
  name it (or each of its words, a `cmd_` prefix left out), or, once the store keeps a coverage summary, those whose
  test contexts ran it. Measured on this engine's brain (main d28f77c): 1,522 edges become 584 by the static rules
  (−1,026, most of which gave each `cli.py` subcommand's feature every CLI test; +88 from imports), 472 with the
  coverage summary (+143, of which 138 ran the code by the contexts); 101 test modules linked instead of 99. New
  `brain coverage [--repo R] --run [-n N] | --from DATA [--write] [--json]` (brain.testcov): the repo's pytest
  suites run under pytest-cov with `--cov-context=test`, the checkout's code first on PYTHONPATH, reduced to
  `<store>/coverage/<repo>.json` (statements, covered lines, and which test modules ran each function, read from the
  data file's SQLite tables; this engine: 90.2 % of 32,296 statements, a 346 KB summary). `brain audit`
  measures `test.coverage` (a module its tests run under 50 %, P2) and the new `feature.tests` (a have or partial
  feature whose module or script no test covers, P2), both outside the scout (ruleset 4); FEATURES.md's Tests cell
  gives each feature's coverage. A summary narrows only what it measured (version 2: every function of each file
  and every test module a context named): a symbol or a test added since, an older or context-less summary, keep
  the names rule; a data file without test contexts is refused, branch data is read from its arcs, the def and
  decorator lines count for no test, the repo's `fail_under` is off for the measure, and the trend reads today's
  summary. Docs: `docs/tests-graph.md`.
- **The module map** (wi-brain-module-map; BRIQUE-4). New `brain modules [--write] [--check] [--json]` (brain.modules):
  each open item's `props.module` and `props.modules_secondary` against the store's registry `modules.yaml`; the
  view `notes/modules_graph.md` (per brick and module: phase, status, items done and open, the secondary ones,
  the gaps, the items outside the tree), written by `brain sync`; `brain check` warns about an open item with no
  module, `none` without a reason, or a module the registry does not know. A store without a registry is not
  concerned. The view goes to the merge driver (`notes/modules_graph.md merge=brain`, in `brain init`'s
  `.gitattributes`). Docs: `docs/modules.md`.

- **The session tree** (wi-brain-session-tree; ST-1, ST-2, scale study gap 19). The SessionStart event records both
  ids, the transcript's (`CLAUDE_CODE_SESSION_ID`) and the desktop app's `local_` id (`CLAUDE_CODE_HOST_SESSION_ID`),
  and the parent, task and short name of the session's own app metadata file (`spawnedFrom`, a closed list of keys;
  nothing else is read and the app's files are never written); the token ledger's brief hash fills the parent in
  without the app. The session record gains `host_id`, `name`, `parent`, `children` and `role` (schema). New `brain
  sessions [tree [ID] | show ID [--report]] [--json]`: both ids, role (master, sub, relay, solo), parent, children
  live/started, state and context against the budget, resolving either id (a prefix of 8 or more) or the short name;
  `show` says what a message would meet (live, idle, archived). The resume pack prints both ids. The cockpit's
  sessions panel shows the short name in Session and gains the Role, Parent, Kids and Ctx (% of the budget) columns,
  the ids in the detail. `brain decision ask`, `answer`, `ack`, `archive` and the question-tool capture stamp
  `host_id` and `machine` (DDR schema); `brain check` refuses a DDR stamped on this machine with a `local_` id that
  matches no session, and warns for one stamped elsewhere or before the stamps (the 9 DDRs with a false `asked.by`).
- **The child's report** (wi-brain-child-report). The Stop hook writes `<BRAIN_HOME>/sessions/<id>.report.json`: the
  session's PRs and its branch's head, the items and DDRs it names, what it waits on, what comes next and its recap,
  read from the last wrap-up, the session record, the plan and the pending DDRs at zero token. `brain sessions tree`
  prints it under each child; `brain sessions show ID --report` prints the child's last final message in full from
  its transcript (the app cuts its end-of-turn note at 400 characters).
- **The master's watch** (wi-brain-master-watch; ST-3, ST-4, ST-10, scale study gap 17). The budget watch treats a
  session that called `start_session` as a master: its budget is its brief's, else config.json `usage.master_budget`
  (new), else the model's window (1M); its steps are 70, 80, 90 and 100 %: the room left in children (measured on the
  family, else 22k a child), then « start no new child, hand over and drain » with a draft hand-over note of the live
  children (both ids, items, state), then « drain only, compact only with no child alive », each with the cost of one
  wake. The governor expires the watch's mark at each `start_session` call and reminds a master past 80 % without
  refusing the call (ST-4); `brain alerts` raises a master past 80 % with live children (source `session`); the
  cockpit colours the master's row at each step.
- **`brain impact [--diff BASE|A..B] [--repo-dir D] [--depth N] [--json]`** (wi-brain-impact-diff): before merge,
  what a change's code carries in the graph. The symbols it touches, from the GitNexus code index (the hunks of the
  diff from the indexed commit matched to the indexed symbols' lines, the query of GitNexus's `detect_changes` sent
  through its MCP `cypher` tool, since `detect_changes` diffs GitNexus's own clone, never this checkout), and their
  callers along the CALLS edges GitNexus resolved (confidence 0.8 and up: the guesses by name left out), `--depth`
  levels (2); the CodeRefs that name them; the nodes relying on those (research_graph's reliance); then a checklist:
  features whose status may change, docs to update (`documented_in`, sections naming a changed file), ADRs (the
  current one of a superseded chain) and specs to re-read, tests to run (the modules covering the touched code, the
  `tested_by` of the relying nodes, the changed test files; one `pytest` line and the CI jobs that run them; the
  features' wider tests counted apart), open items that deliver those features, DDRs pending on them, and the
  touched symbols no CodeRef names. GitNexus's lines, counted from 0, are shifted to git's; a CodeRef whose file the
  change deletes or moves away is touched; a deleted or moved test module never reaches the `pytest` line; a
  malformed CodeRef is left out and named. Without GitNexus (down, the repo not indexed, its indexed commit not here,
  its code map failing) it works at the file level and says so: a Python symbol's CodeRef looked up by the AST of
  both sides, no caller. Docs: `docs/impact.md`.
- **`brain code-map [--json]`** (wi-brain-code-map, the code layer's design §3.7): each active CodeRef of the
  project's stores resolved to its GitNexus node (filePath, name, label: Class, Function, Method, File, or Variable
  for an assignment; a method through its class's HAS_METHOD edge) into `<BRAIN_HOME>/code-map/<project>.json`, with
  the coverage per repo (symbols with a CodeRef over all symbols, files with a CodeRef over the indexed files) and
  each CodeRef that does not resolve, with why. Exit 1 when GitNexus does not answer.
- **The vault's recipients change safely** (wi-brain-vault-rotation, its first part).
  - `brain vault recipient remove NAME`: a plan, then `--write`. It refuses to leave a store with fewer than two
    distinct keys or with no recovery key, each store on its own (a tenant's or a scope's key does not stand for the
    owner's stores), to remove the only recovery key, and to remove a recipient that `vault.tenants` or a scope still
    names. The plan lists the sealed files the removed key still opens.
  - `brain vault recipient add` refuses a declared name unless `--replace` is given (a rotation), and a key another
    name already holds. `--replace` keeps the recipient's kind (a change of kind is refused), its `classes`, `why`
    and host, and copies a new gpg key file even where the old one lies.
  - The canary and the drill prove a key, not a name: a key replaced under the same name is « never sealed » and
    « never drilled » until they run again (state.json keeps each proof's fingerprint; an older drill is tied once to
    the key its canary held).
  - `brain vault reseal [STORE...]`: the plan, then `--apply`. It seals again, to their store's current recipients,
    the sealed files whose recipients changed: it opens each with this machine's device key (its previous one during a
    rotation) or with the key the owner gives, seals it again with the same adapter, replaces the old copy, and records
    `resealed` in the manifest (written atomically). It leaves a file as it is when its store would fall under its
    floors, or would leave a recovery key for one never drilled; an unreadable manifest is that file's error.
  - `brain vault device init --rotate` replaces this machine's key and keeps the previous one in the keystore
    (`device-previous`), which still opens what was sealed to it; the name stays, and a failure puts the keystore back
    as it was. `brain vault device forget-previous` deletes the previous key once config.json declares the new key, no
    longer declares the old one, and nothing waits on a re-seal.
  - `brain vault status` lists the files to re-seal and an unfinished rotation. `brain health vault` fails while a
    removed or replaced key still opens a sealed file or a store has fewer than two distinct keys, and warns when a
    new recipient cannot open one yet or a store is sealed to no recovery key.
  - The runbook gains « Changing the recipients ».
  - YubiKey recipients, each machine's canary seen from the others and post-quantum recipients stay for later.
- **A test never reaches the real keystore or ~/.brain.** Under pytest, `keystore.backend()` refuses this machine's
  keystore unless `BRAIN_TEST_KEYSTORE` asks for it, and `paths.brain_home()` refuses the default ~/.brain: on
  2026-11-03 a test's `monkeypatch.undo()` dropped the conftest's settings and the rest of it rotated the owner's real
  device key (restored the same day; nothing was lost).

- **Lessons in the graph** (wi-brain-lessons-registry). A `Lesson` node type in `brain init`'s default schema (layer
  `lessons`, statuses open, enforced, resolved, regressed, archived; edges `learned_from`, `enforced_by`, `led_to`;
  its `trigger`, `anti_pattern` and `check` required). `brain lesson add|seen|list|rules` (also `brain lessons`):
  `add` writes the node in `nodes/lessons.yaml` and refuses one close to a known lesson (mark it `seen`, or
  `--new`); a lesson seen twice (once if severe) with no open fix, or recurring after its fix (regressed), files an
  item proposal (`priority_proposed`) linked `led_to`, or links the open item whose title is close to it;
  `brain lessons --follow` prints each lesson's lineage (learned from, led to, its PR, enforced by, recurred since
  its fix) and the friction per item by week;
  `brain lesson rules` indexes the iron rules (`Σ-NAME`, `Sigma-NAME`) of each registered repo's tracked Markdown,
  read only. `brain lint lessons [--propose]`: the open lessons a script could check (guard candidates) and those
  that say no `why_not_script`. `docs/lessons.md`.
- **The retro at each close** (wi-brain-lessons-loop). `brain retro ITEM [--record --note ...]`: the friction
  signals of the item's sessions (merges and conflicts, guard refusals from the guards ledger, failed test runs,
  waits, tokens against the estimate, the owner's minutes, pushes to its PRs after opening from the action
  records), the known lessons of the signals that fired and five questions; `--record` writes `props.retro` and
  `props.retro_notes`. `brain retro --wave W`: a wave's deep retro. The close-item procedure gains the step (2b,
  Retro), before the item is ticked and never stopping the close (`Retro: skipped (<why>)` when the store has no
  Lesson type yet or the ledger does not know the item), and a `Retro:` line in its report.
- **A brain's own data is checked by the brain, not by its tests** (wi-brain-test-split). `brain refresh` and
  `brain check` in a brain's own root (its neutral source, `source/packs.yaml`) end with the registry check `brain
  check --all` runs: the registry's keys, `config.json`'s contract, the data classes, the permission hierarchy, the
  stacks, and the ids across every registered project (a `shared_ids` waiver names an id another project holds).
  That check now also renders each bundle the engine ships with the components the registry declares and refuses
  what `brain bundle apply` would (a service without a component, a component without a service), a component whose
  tier class is not `service`, and a stack whose `bundle:` the engine does not ship. A project whose stacks file sits
  in a root this machine does not hold is left out of the stacks with a warning (`stacks.uncloned`), so the verdict
  no longer depends on which repos are cloned here. A brain's repository no longer needs a pytest suite over its own
  graph, records and rendered files: the engine's tests run on fixtures only.

- **What the lessons asked for** (wi-brain-merge-stale-main, wi-brain-guard-public-commit,
  wi-brain-guard-public-chain, wi-brain-guard-heredoc-backslash). `brain merge-check [--base REF] [--no-fetch]
  [--worktree] [--path P] [--json]`: after a merge of main into a branch, a remote base fetched again and, against
  the merge base of main and the branch before the merge, nothing main brought lost (its lines in the journals,
  decision logs, edge files and CHANGELOGs, compared as content; the fields it changed on the graph's nodes; its
  nodes, unless the branch removed them); exit 1 when behind or lost. The public guard gains its `commit` check: in
  a checkout whose branch pushes to a public repo, a commit whose added lines hold a denied
  term, an e-mail address, a home folder or a public.patterns match is refused at the commit, not at the push. Its
  push refusal says to split a `brain check --public ... && git push` call. On Windows, a Bash heredoc holding a
  doubled backslash that writes a file or feeds an interpreter gets a warning in the session's context (never a
  refusal), recorded in the guards ledger as `heredoc:backslash`. `docs/guards.md`, `docs/merge-driver.md`; the
  close-item procedure names `brain merge-check` after a merge of the base.
- **The tests run in parallel** (wi-brain-test-speed, TEST-1). `pytest packages/brain -n auto` (pytest-xdist, now in
  the `test` extra) runs one worker per core; the CI's Windows and Linux jobs do. A test's git repository is a copy of
  a template made once per worker (`conftest.git_init`, behind the `git_repo` and `make_repo` fixtures and every test
  that ran `git init`): 24 ms instead of 329 ms on Windows (47 ms instead of 580 ms for `git_repo`, which copies its
  committed template); the branches guard's tests copy their two repositories, made once per module (84 s to 14 s).
  The test that calls the real docker client is marked `docker` and runs apart, on one process (`-m docker`).
  Measured: on a 16-core Windows machine, 885 s on one process to 165-183 s with `-n auto`; on the CI's Windows
  runners (4 workers), 386-391 s to 173-191 s; on its Linux runner, 42 s to 34 s.
- `brain bundle`'s `docker compose config` no longer crashes when docker compose, killed at its timeout, leaves a
  child holding its scratch folder on Windows (Python 3.10's `TemporaryDirectory` recursed until `RecursionError`):
  docker compose runs from outside the folder (the file given with `-f`), the folder goes by `shutil.rmtree` with its
  errors ignored, and the problem is said (« no answer »).

## 0.2.4 — 2026-11-03

- **A session never installs or runs a third-party kit** (wi-brain-guard-third-party, EXT-6). The new `third-party`
  guard refuses a download fed to a shell or an interpreter (`curl ... | sh`, `wget -qO- ... | bash`, `curl ... |
  python3 -`, `bash <(curl ...)`, `source <(curl ...)`, `sh -c "$(curl ...)"`, `eval "$(curl ...)"`, `iwr ... | iex`,
  `iex (irm ...)`, a WebClient's `DownloadString` to `iex`), `claude plugin install` and `claude plugin marketplace
  add` from outside the owner's list (config.json `adapters.claude.sources`, new; the brain's own marketplace, source
  and folder always pass) and `npx skills add` (also `bunx`, `pnpm dlx`), through wrappers, launchers, nested shells,
  ssh and the Terminal panel. Each refusal is an action for the owner's queue with the call's exact command (`brain
  queue add --kind action --guard <ref>`). `segments()` records what joins its segments (a pipe, a statement, a
  process substitution), so a download to a file then a script with its own stdin passes: replayed on 20,717 past
  commands, no refusal. guard.sh's pre-filter starts Python for `claude plugin` and `skills add`.
- **No conflict marker reaches a commit or a store** (wi-brain-guard-conflict-markers). The new `markers` guard
  refuses a `git commit` (or `merge|rebase|cherry-pick|revert|am --continue`) whose staged lines, commit `-a`'s or an
  earlier `git add`'s, add `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======`, with the file and line; `brain
  check` fails first on a store, journal, decision log or record file that holds one (brain.markers). A setext
  heading in Markdown and a file under a `fixtures` folder pass.
- **The shared files merge by themselves** (wi-brain-generated-merge). `brain merge-driver run %O %A %B %P %L` is a
  local git merge driver for the paths `.gitattributes` gives `merge=brain`, which `brain init` now writes: a
  generated view (``GENERATED by` `` in its first lines, or `_generated_*`) keeps one side, the default branch's when
  one side is its version, and is marked for `brain refresh`, which clears the mark once it passes (`brain check`
  and `brain merge-driver status` name the marked views); `journal.md` and `decisions.md` are unioned, the new dated
  entries in date order, a new entry dated before an old one left as a conflict; `edges/*.yaml` and a CHANGELOG's
  Unreleased section are unioned (a subsection both sides opened becomes one); the other graph YAML is merged entry
  by entry by id (an entry both sides changed, key by key, as `brain item set` writes it); a dated CHANGELOG
  without an Unreleased section is a log, newest first when written so; anything else, and any failure, falls back to `git merge-file`, so a file never loses its markers.
  `brain merge-driver install [--apply]` defines it in a repo's git config, and the installer's new `merge` step runs
  it for the personal brain with the launcher on PATH. `brain merge-driver replay` merges a repo's past merges again
  with `git merge-tree`, as text then with the driver. Docs: `docs/merge-driver.md`.
- **`brain collisions [--all] [--frontier] [--json]`** (wi-brain-collisions): the files each open branch and worktree
  of the project's repos changes (against the default branch, uncommitted changes included, the merge driver's files
  apart), crossed with each startable item's predicted surface (its features' CodeRefs, its module's, the files it
  names; `brain.collisions.SURFACE_HOOKS` for a predictor): the items that can start now, those that wait on a
  branch and its session, those with no known surface.
- **`brain brief ITEM`** (wi-brain-brief-generate): a sub-session's brief from the graph: the item and its props, its
  subgraph, its collisions, the task class's model and effort and the budget (config.json `brief.classes`, a new
  key), the cost estimate, the coordinator's app session id (`--coordinator`, else `$CLAUDE_CODE_HOST_SESSION_ID`),
  the shared notes folder, how to start from the default branch, and the definition of done and the never-list read
  from the owner's rules (`brief.done`, `brief.never`), never written in the engine. The generic template's rules gain
  a « Never » section.

- **The recovery key is typed hidden, and Enter is enough.** `brain vault drill` and `brain vault open --identity -`
  asked age to read the key from the terminal: after Enter, age kept waiting for the end of input (Ctrl+Z alone on a
  line on Windows, Ctrl+D elsewhere), which a terminal may swallow, and timed out after 300 s; the key showed on the
  screen and stayed in the scrollback. The brain now asks for it like a password (`vault.ask_key`: no echo, Enter
  ends it), checks that it is an age identity line and hands it to age on its stdin; it is never written, and a wrong
  line, nothing or Ctrl+C opens nothing. A stdin that is not a terminal gives its first line. gpg still reads its key
  block itself, and its prompt now says how the console ends the input. age missing from a terminal opened before
  its install says to open a new one, and a failure of age names its error, not the « report unexpected or unhelpful
  errors » line it prints last.
- **Structure signals in the scout** (wi-brain-audit-structure; EXT-4, EXT-5). `brain audit --diff` measures the
  shape a change gives the code, from the two trees it already reads, at zero token (`brain.structure`):
  `size.cross` (a code file taken past `max_lines`, NEW), `size.grow` (one already past it grown again, DEFER to the
  debt item), `complexity.cross` and `complexity.grow` (the same for a Python function's cyclomatic complexity,
  computed with `ast`), `dep.adr` (a dependency added to `pyproject.toml`, `requirements*.txt` or `package.json` that
  no decision log of the project names), `shortcut.marker` (a `shortcut:` comment without its ceiling, trigger and
  debt item) and `symptom.cause` (an added `type: ignore` or `noqa` comment, a skipped test, an `except` that
  swallows everything, a sleep, a retry or a longer timeout, with no `Root cause:` line). `--pr-body FILE` gives the
  PR body; it and the range's commit messages are read for `Root cause:` and `Justified: <unit>: <reason>` lines,
  which turn a NEW structure line into `justified` (shown, never blocking). The thresholds are `projects.yaml`
  `audit: {max_lines, complexity}` (default 1000 and 15); the JSON gains `justified` and `structure`.
- **The engine against its pin** (wi-brain-engine-version-skew). `brain check` warns when the running brain or
  research-graph is not `config.json` `engine.pin` (ahead, behind, or the pin's version from another git revision or
  a folder not at the tag: a dev engine, read from the distribution's `direct_url.json`); `brain sync`, `brain
  refresh` and `brain render --write` refuse to write then, unless `--force` (new on sync and refresh; render's also
  replaces foreign files). The refusal ends with the way out in one line: after `brain update`, the tag to set as
  `engine.pin` in the brain's `config.json` and commit; for a dev engine, run the pinned one. A brain with no pin, or a
  pin that is not a release tag, is not compared (`brain.skew`). The upgrade steps of `docs/install.md` and
  `docs/pilot.md` now move the pin before `brain sync`.
- **The cockpit knows its version and offers updates** (wi-brain-tui-update-check, ADR UPD-1 to UPD-3). The title
  bar of `brain tui` always shows the installed version (the text view's header too). Once the screen is drawn, a
  worker reads the release tags of the engine's public repo (`config.json` `engine.repo`, else RoJLD/brain) with
  `git ls-remote`, no token, no credential helper, no prompt; the answer is kept 24 h in `<BRAIN_HOME>/update.json`,
  and offline it says nothing. When a newer tag is out the title reads « brain 0.2.3 · 0.2.4 available » and `u`
  opens `brain update`'s plan in the cockpit's confirmation, run on `y` only.
- **The cockpit applies the brain's installer and relaunches itself** (wi-brain-tui-apply-reload, ADR INST-1 to
  INST-3). A brain declares its own installer in `config.json` `engine.installer` (a path from its root, run without
  arguments for its plan and with `-Apply` to install the engine at the pin; `brain config --check` reports a missing
  file); the engine names none. When the installed engine lags `engine.pin` (a pin PR merged, `-Apply` not run yet)
  and the brain declares one, the title bar reads « brain 0.2.1 · pin v0.2.3: -Apply » (no network needed) and `u`
  opens that installer's plan in the confirmation, then `-Apply` on `y` only; a brain without one (from `brain init`)
  keeps `brain update`. The install never runs inside the cockpit, which on Windows holds files pip must replace
  (PyYAML's `_yaml.pyd`): on `y` it writes `<BRAIN_HOME>/handover/cockpit-<pid>.ps1`, logs it as the owner's action
  and exits; a new console window waits for it to exit, runs the step there (its output stays, a failure says so and
  waits for Enter), then relaunches `brain tui` with the same arguments (elsewhere, an sh script in the cockpit's
  place). `brain update` from the cockpit goes the same way, and so does a queue action's `install.ps1 -Apply`
  (`A`, its `brain queue done` after it in the window). Refused in a Claude Code session's shell.
- **`brain update`**: the plan to the latest tag (the version, its CHANGELOG sections read from the tag, the tag
  installed into `<BRAIN_HOME>/venv` with pip and the `tui` extra kept, the launcher swapped into `<BRAIN_HOME>/bin`
  even while a brain runs, install.ps1's Set-Launcher in Python, and for a pinned brain the `engine.pin` to move by a
  reviewed PR, shown, never done), installed on the owner's yes only (`y` at the prompt, or `--yes`), refused in a
  Claude Code session's shell. `--check` prints the plan and installs nothing; `--json` its data. An editable install
  is left to `git pull`. The tests never read the network (conftest fakes the tags offline).
- **The pilot's settings in the docs**: `docs/install.md` says, before the first session, `BRAIN_MEMORY_SYNC=0`, the
  venv at `%USERPROFILE%\.brain\venv` or `BRAIN_PYTHON`, Git Bash's `HOME` (else `BRAIN_HOME`), telemetry off by
  default, and how to upgrade by hand from a version without `brain update`; `docs/pilot.md` how updates come during the pilot.
- **The engine times itself** (wi-brain-self-timing, the first stage of the opt-in telemetry). Every `brain`
  command and every hook writes one exec event to `<BRAIN_HOME>/ledger/engine/` (project `brain`, task
  `brain <command> [<subcommand>]` or `hook <name>`, `[bash]` for a run that never started Python, the engine's
  version, the duration from the engine's import or from the hook's first bash line, so the interpreter's start
  counts); every error a hook or a command catches through the shared sink (`capture._log_error`) or lets escape
  becomes an error event: its exception class and the engine's `module:function`, never its message. The bash fast
  paths append their own line (`hooks/common.sh`, builtins only) to their own file, apart from the locked Python
  writers. `brain perf --engine` lists the slowest commands and hooks, regressions between engine versions, the
  hooks' blocking time per week against the 1 h trigger of the PERF ADR, and the errors caught; `brain alerts`
  raises a task that caught the same exception 3 times in 24 h (`engine` source; error for a hook, warn for a
  command) on the brain's own project. The engine's events stay out of the projects' ledger files, which `brain
  alerts` and `brain status` read, and the last three months are kept. `BRAIN_SELFTIME=0` turns it off;
  `BRAIN_CAPTURE_TIMING`, which wrote decision times into `errors.log` as errors, is gone. `brain.timing` imports
  `schema`, `secretscan` and `socket` only where they are used, so a hook does not pay for them.
- **The token ledger counts the engine's sessions** (wi-brain-ledger-engine-sessions). A session that ran in a repo
  a project declares under `repos:` (the engine's checkout for a personal brain, its `.claude/worktrees/*`, a
  checkout beside it named `<repo>-wt-<name>` even once removed) is credited to that project, and a sub-session to
  the project of the item its brief names, wherever it ran; before, they landed in « other folders », so `brain
  usage`, the quota pacing and the forecast missed them (`queue.Placer`, also used by the cockpit and `brain queue`).
  A project's own root wins over another project's repo at the same place.
- **Faster hooks** (wi-brain-hook-latency, PERF-1: Python first). The launchers read their JSON with `read` instead
  of `$(cat)`, find Python with `[ -x ]` and `hash` instead of `$(command -v)` (`brain_python`, `hooks/common.sh`),
  pass the JSON as a here-string instead of a pipe, and take the plugin root from their own path: no fork before
  Python. `guard.sh` leaves git that only reads to bash (`git [-C DIR | --no-pager | -P] SUB`, SUB in
  `guards.GIT_READS`: status, log, diff, show, rev-parse, ls-files, blame...; not with `--output` or a pager option;
  any other git, `-c` or `--git-dir` still starts Python), about 30 % of the shell commands that started it.
  `paths.installed_checkout` reads its `file:` URL with `urllib.parse` (`paths.file_url_path`) and once per process:
  a guard no longer imports `urllib.request` (~50 ms). The registry and `permissions.yaml` are read through libyaml
  (`graph.load_yaml`). The exec form of the hooks (`args`, no shell) waits until it is checked on Windows.
- **Fast YAML** (wi-brain-yaml-fast-load). Every YAML read of the engine goes through one helper,
  `research_graph.yamlio` (`graph.load_yaml`, `load_yaml_file`, `load_yaml_all`): libyaml (`CSafeLoader`) when PyYAML
  has it, and a per-process memo keyed by (path, size, mtime_ns) that keeps the data pickled and hands each caller a
  fresh copy; a file written within 2 s of its read is checked against its text's digest. `graph.load_yaml_list`,
  `records.load`, the registry and every module's `safe_load` used the pure-Python parser. `paths.main_checkout`
  keeps its answers for the process (not a None). Numbers from `brain perf --engine` in the PR.
- **Releasing:** `hooks/common.sh`'s `brain_version` moves with `__version__` (a test checks it).
- **The owner's answers, one writer per batch** (wi-brain-answers-lane). Two batches of answers went wrong in two days:
  a shortened label stored as free text, and a BOM that made `--batch` write nothing. Now `brain decision batch`
  writes the questions it prints to the ledger (`asked-<month>.jsonl`), the capture hook ties each answer of the
  question tool to the DDR its question came from (by the id it carries, else its text and header, else its header
  and labels) and writes it to `answer-<month>.jsonl` with the labels as the tool returned them and the owner's notes,
  and `brain decision answer --captured` records the session's captured answers in a worktree on `claude/answers-…`,
  refreshes, opens one PR and merges it, merging main and retrying when it moved (`--retries`, `--no-merge`). `--batch`
  is strict: an inexact label is refused, naming the label it shortens, unless it is marked free text
  (`{"other": ...}`); a BOM is read, UTF-8 or UTF-16. In an agent's session, `answer` and `--batch` record only what
  that session's question tool captured: an answer relayed by a message is never recorded, it is applied and acked.
  The capture also drops the French `(Recommandé)` mark from an ad-hoc question's labels.
- **Decisions by default, then reviewed** (wi-brain-decision-default). `brain decision ask --low-stakes` gives the DDR
  a `default` (its recommendation, final 24 h later): the asking session applies it at once, provisionally; without
  an answer, `brain refresh` or `brain decision defaulted --apply` records it `by: default`, `via: default` at the
  deadline and the hooks announce it « by default ». At the ask and in `brain check`, the mark is refused for a
  decision that touches the owner's rules, scheduled tasks, accounts, keys, money, publication, visibility or
  arming. `brain decision defaulted` is the
  owner's review list (`--seen` from their terminal), with a line in the morning batch and the cockpit's queue panel; `answer ID <option> --again`
  reverses a default. The DDR schema gains `default` and the answer's `via: default`.

## 0.2.3 — 2026-11-03

- **`brain check` passes on a store that holds another repo's links.** Since 0.2.2, `brain sync` derives the Doc, Test
  and Workflow nodes of a project's other repos (those its CodeRefs name) into the store; their anchors are paths of
  that repo (`docs/install.md#...`), which research_graph 0.2.2 read under the store's repo, so `brain check` and
  `brain refresh` failed on every one. Such a node now says `repo: <name>` (written before its anchor), and `brain
  check` gives research_graph check each other repo's checkout (`--repo-path`, research-graph 0.2.3), found as `brain
  audit` finds it: from the project's root, else from its main checkout when the root is a worktree. A repo whose
  checkout is not on the machine is not checked (an advisory). Tested from a main checkout and from a worktree
  (`tests/test_links.py`); research-graph pinned at v0.2.3.

## 0.2.2 — 2026-11-03

- **The hooks read their JSON as UTF-8, whatever the console's codepage** (wi-brain-hook-stdin-utf8). On Windows,
  `python -I` decodes a pipe with the ANSI codepage (cp1252), so a hook got non-ASCII text as mojibake: an emoji
  before « Generated with » came out as letters, and the attribution guard let that line through; every guard read
  accents and « » wrong. The guards, the capture, the governor and the resume hook now read `sys.stdin.buffer` as
  UTF-8 with the BOM a PowerShell pipe adds dropped (`midsession.read_payload`, as the budget and midsession hooks
  already did; wi-brain-hook-stdin-bom), the memory and health hooks drain bytes, every launcher runs
  `python -X utf8 -I` (stdout in UTF-8), and the attribution pattern takes any prefix but letters. Tested from a
  cp1252 stdin and through `guard.sh` with raw UTF-8 (`tests/test_hook_stdin.py`).

- **The suite is green on Linux.** Three places misread Windows shapes off Windows: a PowerShell word's backslash is
  now a path separator wherever `os.path` reads only slashes (`guards.BACKSLASH_SEP`), as PowerShell reads it, so
  `Set-Content {lab}\x` is seen in the production checkout; a `cmd /c` option is slashes and a name without a
  separator (`guards.CMD_OPTION`: `/c`, `//J`, `/XD`), so a Unix absolute path is a target, not an option; and
  `detail.preview` finds `.\install.ps1` by its last part on either separator. The 26 advisory `brain-linux` failures
  of main go away.
- **The Terminal panel meets the shell guards** (wi-brain-guard-terminal-tool). A command that the desktop app's
  `run_in_terminal` types into the owner's Terminal panel ran outside every guard: production checkouts, the owner's
  own actions (`brain usage allow` included), power, attribution, secrets, public pushes and branch names. A
  PreToolUse matcher on `mcp__*terminal__run_in_terminal` now judges it as a shell call (`guard.sh shell`):
  PowerShell on Windows, the panel's shell there, else bash, in the tab's `cwd`, else the session's folder.
- **A brain fresh from `brain init` passes `brain check --all`.** It failed at once with « config.json declares no
  data classes ». A template's `template.yaml` gains `classes`, its own stores, checked when the template loads. The
  generic template classes `memory/` and `records/ddr/` confidential, opted in to `cloud-model`, with a waiver on
  `git-private` until encrypted git is adopted. `init` writes config.json's `classes` block: the template's stores,
  then the engine's machine stores (sealed), then a private catch-all. Its next steps name `brain classes`,
  `brain vault status` and the vault's runbook.
- **The vault's runbook ships with the engine** (`docs/vault.md`): the classes, the owner's steps once per machine,
  the daily canary as a scheduled task for Windows, macOS and Linux, the drill, a lost key. `brain vault status` links
  it. An empty `.gitkeep` holds no data for the classes check.
- **The Business Source License 1.1 from this version** (wi-brain-engine-license). The brain package leaves the MIT
  License: `LICENSE` (BSL 1.1 and its parameters) and `NOTICE` (the credit to keep) sit in `packages/brain`, and
  `pyproject.toml` declares `license = "BUSL-1.1"` and `license-files` (PEP 639: building the package needs setuptools
  77 or later). The Additional Use Grant allows any use, modification and running for your own work and reuse in your
  own products, with a visible credit to Brain and its author and the NOTICE kept; offering it to third parties as a
  hosted or managed service needs a commercial licence. Each version changes to the Apache License 2.0 four years after
  its release. 0.2.0 and 0.2.1 stay under the MIT License, and so does research-graph. The READMEs and
  `docs/pilot.md` say it. Tested (`tests/test_license.py`).
- **The links of a project's other repos** (`brain.links`). A store's CodeRefs may name another registered repo of
  its project (an engine whose code a personal brain describes, say). `brain sync` now also derives that repo's Doc,
  Test and Workflow nodes into the store's `_generated_links.yaml`, from its committed state (the commit `brain audit`
  reads), with the `tested_by` and `documented_in` edges from the nodes that stand for its code: the files of their
  CodeRefs, and a Hook's scripts found there by their `hooks/<name>` (the store's repo renders them from that repo). A
  Skill, a Plugin and the Spec anchors stay the store's repo's. A repo whose checkout is not on the machine is left out,
  and `brain sync` says so. `brain audit` measures `doc.links` and `test.links` of such a repo against that store
  (until now: "no store of its own to hold the links"). A repo no CodeRef names is not derived, so a project's
  production checkouts add nothing.
- Fixed: `code_index:` entries resolve like `repos:` (`projects._resolve_root`): from a project rooted in a worktree, a
  sibling of the main checkout (`../brain`) is found there, not looked for beside the worktree.
- `brain.capture` is documented in the README (the capture hooks' module); `hooks/health.sh` has its end-to-end test;
  `brain lint rules` lost its fallback to a plugin's own `rules/global.md` (the package left the plugin folder).
- **`install.ps1 -Apply` replaces a running launcher.** Sessions' hooks run `brain.exe` many times a minute, and
  Windows refuses to overwrite a running image, so the last step of `-Apply` (the copy to `<BRAIN_HOME>\bin`) failed
  twice. `Set-Launcher` leaves an identical launcher alone, copies a new one beside it and swaps it in with a short
  retry, and renames a still-locked one aside (`brain.exe.old-<time>`, removed on the next run); it prints `same`,
  `copied` or `swapped`. Tested on a running image (`tests/test_installer_launcher.py`).
- **The queue in three bands, ranked by what each entry holds up** (wi-brain-queue-priority). `brain queue` scores
  each entry at zero token: the highest priority and the count of the open items and milestones it holds up, the
  critical path's slip per day of waiting and the nearest milestone (the last `brain forecast`, through
  `forecast.waiting`), a stated deadline above the count, the owner's minutes, its age and the blocking flag. Bands:
  now, this week, when you can. `--explain` shows each term; `brain queue order ID N [--band B] [--clear]` sets the
  owner's own order, which wins; `brain queue add --minutes`, and DDRs gain an optional `minutes`. `brain status`, the
  cockpit's queue panel (Band and Score columns, the band sort first and a band filter) and the zen batches show the
  bands. A denial (perm-, guard-) expires once its session is archived or gone in the desktop app.
- **The owner's display name** (wi-brain-owner-label, UX-16). `config.json` `identity.display_name`
  (`config.name_of`) names the owner in the cockpit's titles, help, confirmations and the text views; `identity.owner`
  stays the id `--by` writes. The queue's title is « {name}'s queue » or « File de {name} » (`tui.json` settings
  `lang`, or `$BRAIN_LANG`), « My queue » when no one is named, and `settings.titles` gives any panel a free title.
- Fixed: a date-typed prop (`due: 2026-11-08`) no longer breaks `brain queue`.
- Fixed: the cockpit reads `tui.json`'s settings again after two writes that share one modification time (Windows'
  coarse clock): its cache keys on the time and the size, and `save_state` clears it.
- **A session's Remote Control and permission mode are the owner's** (wi-brain-guard-session-settings). The guards
  refuse `set_remote_control` and `set_session_permission_mode` under any MCP prefix, and the app's `set_setting` for
  a Remote Control or permission key, whatever the value; the refusal names the `brain queue add --guard` command
  that queues the exact action for the owner, and goes to the guards ledger. `brain.permissions` gains the
  never-grantable category `security-settings` (an allow rule naming those tools, Remote Control or a permission
  mode is refused at every level), and `BRAIN_GUARD_ALLOW` cannot lift it, not even with `all`.
- **The usage governor** (wi-brain-usage-enforce, `brain.governor`, `hooks/governor.sh`): a PreToolUse hook on
  `start_session`, `Agent` and `Workflow` that asks the owner at the quota's WARN and refuses at CRITICAL (both quota
  windows read, the 5-hour one when a reading of it is noted), refuses a new session past the parallel sessions cap
  (config, lowered to what the week's room pays for: room / (wave hours x $ per session-hour) minus the master), a
  new brainstorm past the machine's brainstorms cap (2 by default; a project may lower it for itself, never raise
  it; a brainstorm is known by its brief's `Task class: brainstorm` or `#brainstorm`, or its title), a new session
  or workflow from 90 % of committed memory or while the newest reading is stale (on a machine that notes readings).
  config.json `usage.guard` holds the thresholds and caps; projects.yaml entries gain `usage:`. It reads cached
  state only: its decision takes under 50 ms. `brain usage guard [--json]` shows what each tool would get now;
  `brain usage allow [--hours H] [--reason TEXT]` is the owner's override, which the guards refuse to a session
  (the command and any write of its file). `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` stays the owner's to set
  through their installer.
- **The session record knows ultracode and the task class.** The SR gains `ultracode` (on at any time: the app's
  `ultra_effort_enter` attachment) and `task_class` (the brief's, brainstorm included).
- **`brain init` for a stranger, from a template.** `--template NAME|DIR` (default `generic`, the only one the engine
  ships): a template is data and a manifest (`template.yaml`: name, version, the engine versions it fits, title, the
  graph stores it starts, a list of `{name, store, schema}` with the main store first and only research_graph's
  default schema for now, and the files it renders with `{owner}`, `{owner_q}`, `{name}`, `{title_q}`), never code;
  the plan stays local, a list of steps a later one (the owner's repos and data store) can join; a bad manifest, an
  engine outside its range or a template missing what config.json names plans nothing. config.json records it (`template`, a new key
  of the schema). `--owner` defaults to the owner of the folder's config.json. The generic template's files moved to
  `templates/generic/`.
- **The generic store holds the records** (GT-2, wi-brain-init-records-layer). A template's `schema: default` is
  the brain's base (`templates/schemas/default.yaml`): the work, decisions and records layers, so that `brain sync`
  turns a new brain's DDRs, sessions and actions into nodes from the first sync; `research_graph init` builds the
  store, then `brain init` writes this schema in its place (a new store only).
- **Publishable by construction.** The generic template writes `boundary.yaml` (every file's side, `readiness_max: 0`,
  `src/`, `tests/` and `fixtures/` on the engine side), `fixtures/README.md`, a `README.md` and `.gitattributes` (LF:
  the hooks' shell scripts), and config.json `public` (no repo; `deny`: the owner, this machine's user and host,
  leaving out names too common to deny). `brain check` runs the boundary's check and the engine side's public scan
  wherever a boundary.yaml is (`brain.public.gate`): a file no rule classifies, or a denied term, a secret, an e-mail
  address or a home folder in what may be published, fails it from the first commit. `projects.yaml` waives the
  rendered plugin in `brain audit`, so a fresh brain carries no debt of the engine's.
- **The stranger test.** `installer/stranger_test.py` installs a tag (or, `--pre-tag`, a branch with research-graph
  from the same ref) into a fresh venv, isolated from its caller (its own home, BRAIN_HOME, Claude and git config, a
  PATH with no docker, Git's bash for the hooks on Windows), runs the Lite scenario as an invented owner and scans
  every output and file for the terms given with `--deny`; its verdict is a pilot's go. `docs/install.md` (Windows
  from zero, Linux and macOS) and `docs/pilot.md` (what to try, how to report an issue) are the tester's.

## 0.2.1 — 2026-11-03

- **A new brain gets its own Claude Code plugin.** `brain init` renders a local marketplace in the new brain: it
  writes `source/packs.yaml` (the marketplace's owner, one core pack with the engine's hooks) and config.json
  `adapters.claude` (the marketplace `brain`, the plugin `brain-core`, no `source`), then, after the store,
  `.claude-plugin/marketplace.json` and `plugins/brain-core/` by the code of `brain render --target claude --write`,
  so `brain check` passes at once; a rendered file that exists and differs is kept. The owner adds the marketplace
  once (`claude plugin marketplace add <the brain's folder>`, then `claude plugin install brain-core@brain`): a local
  marketplace's plugin is loaded in place, so its hooks are those of the installed engine, and `brain sync` renders
  them again after an upgrade. Nothing of the owner's leaves the machine, nothing is published.
## 0.2.0 — 2026-11-03

The brain command, published as this repo's second distribution, from the personal brain it was written in (a fresh
history: its code, Claude hooks, tests and installer at their targets, then the changes below).

- **The digest dates closures at any hour.** `digest.git_closures` bounds `git log` by full days at midnight and keeps
  the commits whose own day falls in the window: a bare `--since=<day>` was read at the current time of day, so a
  closure from the first day of margin showed up or not depending on the hour (failing before noon UTC).
- **Python 3.10 reads pyproject.toml.** The `tomli` backport is a dependency below 3.11, and `brain.inventory` falls
  back to it: the audit, the scout and the links measured nothing on 3.10 without `tomllib`.
- **A package of its own.** `packages/brain`: `pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.0#subdirectory=packages/brain"`;
  it depends on `research-graph` at the same tag. The Claude hooks are package data
  (`src/brain/adapters/claude/hooks/`), copied into the owner's own plugin by `brain render --target claude`; the
  engine's narrow allow rules too (`src/brain/adapters/claude/allow-rules.txt`, read by `brain permissions`).
- **The personal brain, found from anywhere.** `$BRAIN_PERSONAL`, then the machine's pointer
  `<BRAIN_HOME>/personal.json` (`{"root": ...}`), join the places `config.json`, `projects.yaml` and `permissions.yaml`
  are looked for (after `$CLAUDE_BRAIN_DIR`; the pointer after the repo acted on, so a worktree reads its own files),
  and the repo acted on falls back to the personal brain (`brain.paths.bases`, `personal_root`). `inject-rules.sh`
  reads the pointer too; `brain config` shows it.
- **The hooks find the installed engine.** Every hook's launcher tries `$BRAIN_PYTHON`, then the brain command's venv
  (`<BRAIN_HOME>/venv`), then `python3` and `python`: a plugin folder without the package runs the installed one.
- **`brain init`**: a new personal brain from `src/brain/templates/` (config.json v1 with the engine pinned at this
  tag and the Lite tier, projects.yaml, the graph store by `research_graph init --owner`, journal, ADR log, neutral
  starter rules, CLAUDE.md, memory and records) and the machine's pointer; a plan, `--apply` writes it, nothing is
  overwritten.
- **The installer** (`installer/install.ps1`) installs the command at the tag config.json `engine.pin` names (or its
  own version without a personal brain; `-Engine` for another pip spec), takes the personal brain from `-Personal`
  (its main checkout, never a worktree), writes the pointer, and runs the Claude steps only when config.json names a
  marketplace and rules.
- **`brain check --public --history`** also reads the commits' messages (every check of a line) and their author's
  and committer's e-mail addresses (a no-reply one passes).
- Tests: the ones that read the personal brain's own files stay there; the permission tests read a neutral fixture
  (`tests/fixtures/permissions.yaml`).
