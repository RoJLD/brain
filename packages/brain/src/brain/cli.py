"""``brain``: one command for {owner}'s records and backlogs, at zero token (Q3, 2026-10-30).

  brain record sr   [--session ID | --transcript PATH] [--summary TEXT] [--item ID]... [--closed] [--replace]
  brain record ar   --import [--session ID] [--since DATE] | --from-transcript PATH | --session ID --kind K ...
  brain record ddr  --file DDR.yaml | --title T --question Q --option "label: consequences"... --why W ...
                    | --id ID [--answer LABEL]... [--other TEXT] [--read] [--applied WHERE]... | --import
  brain record backfill [--since DATE] [--until DATE] [--quiet-hours N] [--update] [--no-subagents] [--no-ledger]
                    [--dry-run]   the SRs and ARs of every transcript on this machine (pushes, PRs, the commits
                    the repos' history confirms, the ledger's live captures); a rerun writes nothing new
  brain record check | sync
  brain item add ID --title T [--priority P1 [--reason R]] [--spec S] [--after ID]... [--milestone M] [--adr A]
                 [--prop k=v]...         without --milestone, prints the milestone the signals suggest
  brain item set ID key=value...
  brain item close ID --pr "repo #N" [--outcome TEXT]
  brain item link FROM TYPE TO [--prop k=v]...   an edge (with props: enforced_by's scope)
  brain item unlink FROM TO   remove the curated edge between two nodes (re-typing one: unlink, then link)
  brain features list [--status S] [--domain D] [--repo R] [--module M] [--value V] [--json]
  brain features search TEXT... [--limit N] [--json] | show ID [--json]   the feature matrix through its SQLite
                 index (full-text search, FTS5), a cache in <BRAIN_HOME>/features rebuilt when the store changes
  brain features add ID --title T --domain D [--status planned] [--value medium] [--repo R] [--module M]
                 [--code PATH[::SYMBOL]]... [--test T]... [--doc D]... [--spec S]... [--adr A]... [--parent F]
                 [--item WI]... [--prop k=v]...   | link ID [the same edges] | set ID key=value...
  brain features render [--write] [--repo R --out PATH]   FEATURES.md, the matrix by domain (no --write: exit 1
                 when the file is not the render); sync [--offline]: statuses named by merged PRs
                 ("feat-brain-x: have"), then FEATURES.md
  brain milestone suggest [--only ID]... [--write]   the open items attached to no milestone, each with its proposal
                 (props.milestone_proposed, never overwritten) or a new one: the milestone most items of its spec
                 belong to, then its depends_on neighbours', then its theme's; --write stores the new ones (ms-x?)
  brain milestone apply [--only ID]... [--skip ID]... [--set ID=MS]... [--write]   once {owner} has validated: the
                 part_of edges of the proposals (or of the values set), the proposals cleared; without --write, the
                 plan
  brain milestone add ID --title T --trigger TR [--item ID]... [--parent MS] --why W [--option "A: c"]... [--ddr D]
                 a new milestone through the decision queue: the first run asks {owner}, the same command once the
                 creation is chosen writes the Milestone and its items' part_of edges
  brain spec activate [--write] [--all] [--json]   each proposed spec, ready or what keeps it proposed: a spec turns
                 active once a decision is recorded (a DDR names it in links.specs, or props.validated or decided),
                 every DDR naming it is answered and acked, it has no props.open, its document no unanswered question
                 and no line <!-- thinking: open[: note] --> outside code; props.keep_proposed opts out; --write
                 flips the ready ones (status, props.activated, props.activated_by), as brain sync does by itself
  brain journal add [LINE|-|@FILE]... [--title T]   a new dated entry, or lines at the end of today's (append-only)
  brain adr new TITLE --context C --decision D --why W --revisit R [--why-not-script S] [--decides ID]...
  brain adr new --reverses ADR --trigger T --decision D --why W --migration M ...   REVERSAL: <title>, supersedes
  brain decision ask --title T --question Q --option "A: consequences"... --why W [--multi] [--blocking] ...
                 [--low-stakes]: applied at once, provisionally, final by default 24 h later without an answer;
                 refused on money, keys, visibility, publication, accounts, arming, rules and scheduled tasks
  brain decision pending [--all] [--json]     what waits on {owner}: the queue, items' props.open, spec questions
  brain decision answer ID CHOICE... [--other TEXT]   {owner}'s choice (label, number or start of the label)
  brain decision answer --batch @FILE|-|JSON [--via ask-tool --by {owner}]   a morning session's answers in one call:
                 {"<DDR id or question>": "<label>" | ["<label>"...] | {"choices", "other", "notes"}}; exact labels
                 ("(Recommandé)" ignored, a multi_select's labels joined by ", "), {owner}'s own text only as
                 {"other": "..."}; a BOM is fine; every key is checked before any DDR is written
  brain decision answer --captured [--session ID] [--no-merge] [--retries 3] [--dry-run]   the answers this
                 session's question tool captured (each tied to the DDR brain decision batch printed), recorded in a
                 worktree, one PR, merged with its retries; in an agent's session an answer relayed by a message is
                 never recorded (apply it, then ack)
  brain decision defaulted [--all] [--apply] [--seen [ID...]] [--json]   the review list: the decisions taken by
                 default, the provisional ones, the reversed ones (reverse one: answer ID <option> --again)
  brain decision batch [--project P | --all] [--size 4] [--zen [--minutes 5]] [--json]   the zen mode: the pending
                 decisions in batches for the question tool (AskUserQuestion: up to 4 questions, a header of 12
                 characters, 2 to 4 options, the recommended one first and marked "(Recommandé)"), the blocking ones
                 first and flagged, then by what they unblock; a brainstorm's numbered questions (Q1.., BRIQUE-1..)
                 together, else one item's or one spec's; --json: each batch's questions, the tool's input as is, and
                 its DDR ids; --zen: the morning digest, the batches that fit in --minutes (0: all), then the rest
  brain decision ack ID --applied WHERE...    read and applied (ADR, item, spec), then archived (--keep: not yet)
  brain decision archive [ID]... | view [--all] [--write] | announce
                 a --blocking ask is also sent through the notification channels (brain notify; --no-notify: not)
  brain queue [--project P | --all] [--kind decision|action|permission]... [--days N] [--no-graph] [--no-transcripts]
              [--explain] [--json]   {owner}'s queue: decisions (DDRs, items' props.open, spec questions), actions
                         only they may do (keys, money, arming, visibility, accounts, scheduled tasks, legal reading)
                         and permissions an agent lacked (denied tool calls in the last N days of transcripts, default
                         7; expired once their session is archived or gone); ranked in three bands (now, this week,
                         when you can) by a zero-token score of what each holds up: the priority and count of the open
                         items and milestones downstream, the critical path's slip per day of waiting and the nearest
                         milestone (the last brain forecast), a stated deadline, the minutes it takes, its age;
                         --explain shows each term
  brain queue order ID [N] [--band now|week|later] [--clear]   {owner}'s own order: first in its band, at position N
  brain queue add --kind action|permission --title T --what W [--item ID]... [--blocking] [--due D] [--minutes N]
                 a DDR of that kind (--due: a stated deadline, it weighs above the count; --minutes: the effort)
  brain queue add --guard guard-ID [--item ID]...   a refusal of the owner, power or third-party guard as an action:
                 its title, exact command (the question; and the command when Apply runs it) and reason from the
                 guards ledger
  brain queue done ID [--note TEXT]   {owner} did the action or granted the permission (a denial or a guard refusal:
                 until refused again)
  brain queue apply ID   {owner}'s Apply: the action's exact command (queue add --command CMD [--cwd DIR], else the one
                 its text names) shown, an install.ps1 -Apply's plan run first, run on the owner's y, logged as their action in
                 $BRAIN_HOME/ledger/cockpit-<month>.jsonl, then queue done; refused in a Claude Code session's shell
  brain sync [--all] [--offline]   the ready proposed specs turned active (brain spec activate --write), then
                        research_graph sync --write, the records' graph view, the decision queue view,
                        the links graph (Doc, Test and Workflow nodes, documented_in, tested_by and runs, brain.links),
                        the features' statuses from merged PRs (gh; not with --offline) and FEATURES.md, kanban --write
  brain check [--all]   the records (schema, ids, secret scan), the open items attached to no milestone (a warning),
                        the proposed specs ready to turn active (a warning), the hard-rule ratio (Rule nodes with an enforced_by edge; a soft rule is a warning), a stale
                        links graph (a warning), then research_graph check (given the project's other repos'
                        checkouts, where the anchors of their Doc, Test and Workflow nodes are read); --all: every
                        project's, then the registry
                        (its keys, repos, stacks, code_index), the tier registry (every capability and stack declares
                        its class, profile, requirements, cost and fallback) and the ids, unique across every store of
                        every project (an id shared on purpose is waived under shared_ids:)
  brain check --public [--repo DIR] [--remote NAME] [--history] [--engine] [--json]   before a push to a public repo
                        (config.json public.repos), at zero token: no denied term (public.deny), secret, e-mail or home
                        folder, data or sealed file, nor a domain's patterns (public.patterns, public.refuse) in the
                        tracked files, and with --history in the commits not on the remote yet (gitleaks too when on
                        the PATH); green with --history, it stamps HEAD for the public guard on git push; --engine:
                        the files brain boundary sends to the engine, in this checkout (a dry run)
  brain refresh [--all] [--offline]   sync, then check, for this project's stores or every registered project's (--all: and the
                        registry and the ids, as check --all); check and refresh end with brain tidy's line when its
                        repos hold stale worktrees or merged branches
  brain tidy [--project P | --all] [--remote] [--apply] [--json]   at zero token, the project's repos: the stale
                        worktrees (clean, detached or on a merged branch, their desktop-app session archived or gone,
                        else idle 24 h), the local branches merged into the default branch, and with --remote origin's
                        merged branches (git ls-remote, read only); listed, then removed with --apply (git worktree
                        remove after the untracked junctions they hold, git branch -d; never --force, -D, an unmerged
                        branch or a dirty worktree; a production checkout: those two only); --remote --apply deletes
                        the remote ones (git push origin --delete) only outside a Claude Code session, where it prints
                        the brain queue add that puts the exact command to {owner}; --json: the plan
  brain merge-driver run BASE OURS THEIRS PATH [SIZE]   git's entry (merge.brain.driver ... %O %A %B %P %L) for the
                        paths .gitattributes gives merge=brain: a generated view keeps one side (the default branch's
                        when one side is its version) and is marked for brain refresh; journal.md and decisions.md
                        are unioned, new entries in date order; edges/*.yaml and a CHANGELOG's Unreleased section are
                        unioned; other graph YAML is merged by id; anything else, and any failure, as git merge-file
  brain merge-driver install [--repo R] [--launcher PATH] [--apply] [--json]   defines the driver in the repo's git
                        config (shared by its worktrees; the installer runs it), checks .gitattributes names it
  brain merge-driver status [--json] | replay [MERGE | OURS..THEIRS]... [--since DATE] [--repo R] [--json]
                        the views waiting for brain refresh here; past merges merged again by git merge-tree, as
                        text then with the driver (nothing checked out): what conflicted before and after
  brain collisions [--all] [--json]   at zero token: the files each open branch and worktree of the project's repos
                        touches (against the default branch, uncommitted changes included), crossed with each
                        startable item's predicted surface (its features' CodeRefs, its module, the files it names):
                        the items that can start now, and those that wait on a branch (and its session)
  brain brief ITEM [--class trivial|standard|strategic] [--budget 400k] [--coordinator ID] [--notes DIR] [--write F]
                        a sub-session's brief from the graph: the item, its decided props and open questions, its
                        subgraph, its specs and ADRs, its files and collisions, the class's model and effort
                        (config.json brief.classes), the budget, the cost estimate, the coordinator's id (--coordinator,
                        else $CLAUDE_CODE_HOST_SESSION_ID), the shared notes folder, and the definition of done and
                        the never-list read from {owner}'s rules
  brain coverage [--repo R] [--run [-n N] | --from DATA [--cwd DIR]] [--python PY] [--write] [--json]
                        a repo's line coverage: --run runs its pytest suites (from each suite's pytest configuration)
                        under pytest-cov with test contexts, --from reads a coverage data file made elsewhere (the
                        CI's .coverage, run with --cov-context=test); the summary (totals; per file its statements,
                        covered lines and the test modules that ran each function) printed, and with --write kept in
                        the store as coverage/<repo>.json: brain sync links a CodeRef's symbol to the tests that ran
                        it, brain audit measures test.coverage, FEATURES.md shows each feature's coverage
  brain sessions [tree [ID] | show ID [--report]] [--hours H] [--all] [--json]   the session tree at zero token, from
                        the desktop app's session files (a closed list of keys, read only), the SessionStart events
                        and the briefs' hash: both ids of each session (the app's local_ id, the transcript's), its
                        short name, role (master, sub, relay, solo), parent, children live/started, state and context
                        against its budget (the brief's; a master's: usage.master_budget, else the model's window);
                        tree: the families with a live member, each child's end-of-turn report (its PRs, head, items,
                        DDRs, what it waits on, what comes next); show: one session, by either id (a prefix of 8 or
                        more) or its short name, and what a message would meet (live, idle, archived); --report: its
                        last final message in full, read from its transcript
  brain status [--all] [--quick] [--json]   each project's indicators at zero token: items by status and priority,
                 the frontier, decisions waiting on {owner}, milestones, audit debt, stacks, code index, its open
                 alerts (brain alerts), journals, records and ledgers; --all adds the totals and the ids shared across
                 stores; --quick reads the files only (no audit, stack, code index or scheduler probe)
  brain projects [--keys] [--json]   the registry resolved: each project's stores, journals, decision logs, ledgers,
                 repos, stacks, code index and plugin; --keys: every key an entry may hold
  brain init [DIR] [--owner NAME] [--template NAME|DIR] [--kind person|team] [--tenant ID] [--tier lite|default]
                 [--name NAME] [--apply]   a new personal brain from a template (generic by default), in DIR
                 (default: here): config.json (its public.deny: the owner, this machine's user and host), projects.yaml,
                 boundary.yaml (readiness_max 0: brain check refuses anything private in src/, tests/, fixtures/), the
                 graph store, journal, ADR log, starter rules, CLAUDE.md, README.md, the local Claude marketplace,
                 memory and records, and this machine's pointer <BRAIN_HOME>/personal.json when it has none; --owner
                 defaults to DIR's config.json identity.owner; a plan, --apply writes it; never overwrites
  brain config [--json] [--keys] [--check]   the personal brain's config.json resolved (owner, registry, rules,
                 memory, records, engine pin, public repos and how many denied terms, secrets by name, the machine's
                 pointer); --keys: every key it may hold (from schemas/config.schema.json); --check: exit 1 when it
                 breaks the contract
  brain profile [--json] [--quick]   (alias brain doctor) this machine's facts at zero token, each probe with its
                 own timeout (CPU, memory, GPUs and their VRAM, the inference backend, disks and BRAIN_HOME's size,
                 tools, container runtime, Kubernetes context, disk encryption), the active profile and its overrides,
                 each capability's and stack's state (on, to install, fallback, missing, off, unavailable, planned),
                 the Recommended profile computed for this machine and what it would add; --json: the machines
                 brick's inventory fields and a brain block, for the cockpit; --quick: no probe that starts a program
  brain profile list | show lite|default|recommended|custom [--json]   each profile's entries (Lite, Défaut,
                 Recommandé computed for this machine, Personnalisable: this machine's overrides); show: one profile's
                 entries with their class, requirements, cost, fallback and state (brain.tiers, tiers.yaml)
  brain profile set [lite|default|recommended] [--with ID]... [--without ID]... [--apply]   the plan of this
                 machine's profile (recommended: the set this machine allows, frozen into the overrides); --apply
                 writes it to $BRAIN_HOME/profile.json, and a second apply changes nothing; no base: the current one
                 with these overrides; --with all: every built entry; install.ps1 -Tier / -With / -Without runs it
  brain profile render [the same]   what install.ps1 reads, as JSON: the pip extras the profile wants, those
                 installed outside it, the stacks on and off
  brain boundary [--check] [--side engine|personal|claude|generated] [--readiness] [--json]   every tracked file's
                 side by boundary.yaml (engine: leaves for the public engine repo, at its target), and the readiness
                 of the engine side: the terms of config.json public.deny found in its files; --check: exit 1 on a
                 file no rule classifies; --side: that side's files; --readiness: the hits per file
  brain render [--target claude|agents|cursor|gemini|antigravity|grok|hermes] [--project P] [--repo DIR] [--out DIR]
                 [--write | --check] [--force] [--json]   the neutral source (source/: rules with scope and id,
                 procedures, MCP servers, packs) written as an agent's own files: claude, the marketplace and its
                 plugins in the brain's repo (byte for byte the hand-written step 1; no marker, brain check refuses a
                 hand edit); agents, the project's AGENTS.md (its chain flattened: global, ancestors, its CLAUDE.md
                 last) and .agents/skills; cursor, gemini, antigravity, grok and hermes, the base plus each tool's MCP
                 settings (JSON merged, never replaced); no flag: the plan; --write: into the brain's and the
                 project's repo (never a production checkout, never the home folder; --force replaces a file it did
                 not write); --check: exit 1 when an output is not current; --out: a dry render into a folder
  brain classes [PATH...] [--check] [--json] [--suggest] [--matrix]   every store's data class (config.json
                 classes.stores: public, private, confidential, sealed, resident, secret, tenant:<id>), its tracked
                 files and the exits it takes; PATH: the store and class of each path; --check: exit 1 on a tracked
                 file or an engine store without a class, an exit its class forbids, tracked files its class keeps
                 out of the remote in clear, a class under its scope floor (waivers printed); --suggest: a starting
                 block to edit; --matrix: how each class may take each exit (brain.classes)
  brain vault status [--json]   adapters (age, gpg), the keystore, this machine's device key (public facts), every
                 recipient with its fingerprint and last canary, the last seal per store, and the steps left to the
                 owner with their exact commands
  brain vault seal STORE [PATH...] [--out FILE] [--adapter age|gpg]   seal a store (its declared content, or the
                 paths) client-side to its recipients, public keys only, unattended; refuses a resident or secret
                 store and fewer than two recipients; a manifest beside the sealed file
  brain vault canary   seal a fresh nonce to each recipient alone, open the one this machine's device key opens,
                 compare the digests ($BRAIN_HOME/vault/state.json): the daily proof, the scheduled task's command
  brain vault recipient add NAME --kind device|recovery|hardware|person (--age KEY | --gpg FILE) [--host H]
                 [--write]   declare a public recipient in config.json (a plan without --write); refuses a private key
  brain vault device init [--name N] [--adapter age|gpg]   this machine's device key, created straight into the OS
                 keystore; prints its public half only (the owner's terminal only)
  brain vault open FILE [--out DIR] [--identity FILE|-]   open a sealed file with the device key, a key file or a
                 key typed hidden (-) (the owner's terminal only: refused in an agent session)
  brain vault drill RECIPIENT [--identity FILE|-]   open that recipient's canary with its key and record the proof:
                 the recovery key's yearly drill (the owner's terminal only)
  brain permissions [--project P | --all] [--machine H] [--session S] [--explain RULE|perm-ID] [--json]   the
                 permission hierarchy (engine allow-rules.txt, then permissions.yaml: global, profile, machine,
                 tenant, project, local, session): the effective allow / ask / deny list and where each rule comes
                 from, the guards (the hard deny layer), the never-grantable categories, and each settings file's state
  brain permissions check | render [--level user|project|local|session] [--repo DIR] [--write] [--json]
                 | grant [perm-ID] [--call C] --rule R --why W [--global|--project P|--machine H|...] [--dry-run]
                 render: an adapter's files (Claude Code's; adds the missing rules, never removes one; the user file
                 is install.ps1 -Apply's); grant: a rule appended in this branch, reviewed by PR (no --rule: proposals)
  brain resume [--project P | --all] [--budget N] [--write] [--offline] [--health] [--notes DIR]...
                 the resume pack: the project's present state from the graph, records, journal and git, ordered from
                 stable to volatile (milestones, frontier and P0/P1, decisions, open PRs, journal, hand-over notes,
                 then the date); --budget cuts from the volatile end (default 3000 tokens, 0: no limit); --write
                 keeps it in <BRAIN_HOME>/resume/<project>.md, whose age the SessionStart hook reports in one line
  brain lint rules [--project P | --all] [--json] [--propose [--max N] [--dry-run]]
                 at zero token: the tokens injected per session (global rules against the 10,000-character hook cap,
                 CLAUDE.md files, memory index, skill descriptions), duplicates between rule files, procedures
                 (script candidates), rules a hook could check (guard candidates), the hard-rule ratio (enforced_by);
                 --propose files one DDR per candidate rule or pair, at most N (8) rules-lint DDRs pending at once;
                 exit 1 when the injected rules pass the hook cap
  brain digest [--project P | --all] [--since WHEN] [--until WHEN] [--budget N] [--write] [--offline] [--json]
                 the digest: what happened in a window, newest first, from the graph (milestones reached, items
                 closed), the ADRs, the DDRs, the SRs, gh (merged PRs; --offline skips them) and the journal; WHEN is
                 YYYY-MM-DD, today, yesterday, last-week, last-month or a reached milestone's id (default: last-week
                 to today); --budget lowers the sections from full text to one line each to counts, the journal
                 first (default 4000 tokens, 0: no limit); --write keeps it in
                 <BRAIN_HOME>/digest/<project>/<since>_<until>.md, which the resume pack names; --json: the records
  brain notify send [MESSAGE|-|@FILE] --level info|warn|error|critical [--title T] [--source S] [--key K]
                 [--link URL] [--channel C]... [--force] [--dry-run] [--json]
                 through the project's route for that level (projects.yaml notify:): ntfy, Telegram, e-mail, the
                 first that delivers or every one; --channel: these channels only; --key: not again within the
                 throttle (--force: anyway); --dry-run: print what would be sent; exit 1 when nothing delivered
  brain notify status [--all]     channels (their environment variables set or missing, never their values), routes
  brain notify setup ntfy|telegram|email|CHANNEL [--find-chat]   a channel's setup steps; --find-chat lists the
                 chats that wrote to the Telegram bot (it sends nothing)
  brain alerts [--project P | --all] [--quick] [--json] [--fail-on LEVEL] [--notify [--dry-run]]
                 the open alerts of each project, at zero token: the scheduler's tasks (missed passes against their
                 cadence, 2 before an alert; killed, failed, disabled, silent), the exec ledger, watched stacks, the
                 code index, the audit debt above the written view, the project's alert events and files (brain
                 status shows them in the project's section); --quick: the files and events only; --fail-on: exit 1
                 when one is open at that level or above; --notify: the pass a scheduled task runs, which sends each
                 new, risen or failed alert through brain notify at its level (resolved ones at info) and records
                 the changes in $BRAIN_HOME/alerts (--dry-run: what it would send, nothing recorded)
  brain alerts raise KEY [MESSAGE|-|@FILE] --level L [--task T] [--source S] [--code C] [--link URL]
  brain alerts resolve KEY [MESSAGE] [--level L]   a project's alert event (kind alert of the event schema) in
                 $BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl, what its writers call instead of a tracked alerts file
  brain capture EVENT [git|gh]   the hooks' entry (hook JSON on stdin; prints nothing)
  brain memory status [--offline]   what a memory sync would do, note by note (export, import, conflict, kept),
                                  against main fetched now (--offline: as last fetched); writes nothing
  brain memory sync [--export-only]   the sync the SessionEnd hook starts detached, now and in the foreground:
                                  import what only main changed, then the secret scan and the export of what only this
                                  machine changed to memory/<machine>/<date> and its PR (never main); exit 1 when the
                                  export is refused or the sync fails (brain.memory)
  brain audit [--all] [--repo R]... [-v] [--json] [--trend [N]] [--fail-on P] [--write] [--items]   what misses
                 the standard per repo and module (zero token): P0 false statements, P1 gaps on production paths
  brain audit --diff [BASE|A..B] [--repo-dir D] [--store DIR] [--limit N]   the scout: what the modules a change
                 touches miss (NEW, LEFT, DEFER); exit 1 when something is to fix in the PR
  brain up [STACK]... [--force]   start stacks after their dependencies, waiting for health; a healthy one is
                                  untouched, unless named with --force (its start command runs again) or a Compose
                                  stack (docker compose up -d always runs: it applies a changed compose file)
  brain down [STACK]...     stop stacks, in reverse dependency order (up and down --project P: P's stacks)
  brain health [STACK]... [--all]   check the named stacks, the watched ones, or every one; starts nothing; a
                                  Compose stack whose containers differ from its compose file is STALE, one outside
                                  this machine's profile and not up is OFF (not a failure); the name
                                  code-index (or --all) checks the code index: STALE when a repo's branch moved
                                  past its indexed commit, it was never indexed or GitNexus lost it; --project P:
                                  every stack of P, then P's code index; a bundle's name (sovereign) stands for its
                                  components in up, down and health; the name vault (or --all): every canary sealed
                                  within 26 h and opened by this machine's device key, two recipients at least
                                  (brain.vault), OFF without a vault block or without age and gpg
  brain bundle plan [BUNDLE]... [--json]   a Compose bundle the engine ships (sovereign: OpenTelemetry collector,
                                  Prometheus, Loki, Grafana, Qdrant): checks (ports on 127.0.0.1 only, images pinned
                                  by digest, docker compose config), the files, folders and images, and what the apply
                                  does with each component; writes and starts nothing (exit 1 on a problem)
  brain bundle apply [BUNDLE]... [--no-start]   render it into <BRAIN_HOME>/stacks/<bundle> (data where each
                                  component's placement says), pull the missing images, brain up its components; a
                                  component whose secret file is missing waits; a second apply changes nothing
  brain index [REPO]... [--all] [--stale]   have GitNexus (re)index the repos declared under code_index: (a snapshot
                                  of each one's branch in GitNexus's own store, then /api/analyze with embeddings),
                                  recording the indexed commit in $BRAIN_HOME/code-index.json; --stale: only those
                                  not indexed at their branch head; no name and no flag: each repo's state;
                                  --project P: only P's repos
  brain timed [--task T] [--project P] [--version V] [--shell] [--quiet] -- COMMAND...
                 run COMMAND (input and output untouched, exit code passed through) and append its event (start, end,
                 duration, exit, host, project, task, version) to $BRAIN_HOME/ledger/exec-<yyyy-mm>.jsonl, one line
                 under a lock (brain.timing; projects import brain.timing.timed, a decorator and context manager)
  brain perf [--project P] [--since 28d|4w|DATE] [--task TEXT] [--top N] [--from PATH]... [--json]
                 the slowest steps, the trends, the regressions after a change and the time lost per week
  brain usage [--project P | --all] [--since WHEN] [--until WHEN] [--by DIM | --report daily|weekly] [--top N]
                 [--no-scan | --rescan] [--json]   the token ledger at zero token ($BRAIN_HOME/usage/sessions.json,
                 scanned from the transcripts that changed): the sessions' tokens and cost at API prices by project,
                 item, pr, class, kind, theme, milestone, model, phase, tool, command, skill, session, family (a
                 session and its sub-sessions), day or week, with the distribution per unit (median, p25-p75, p90),
                 and the script candidates (3-step sequences repeated across sessions); WHEN: Nd, Nw, today,
                 yesterday, last-week, last-month or YYYY-MM-DD (default 7d)
  brain usage quota [--observe PCT [--resets TIME] [--at TIME]] [--window week|5h] [--no-scan] [--json]
                 the plan's quota (brain.quota): --observe notes a get_usage reading (percent used, read at --at,
                 default now; the window resets at --resets, get_usage's resetsAt, default the last reading's moved
                 by whole weeks) in $BRAIN_HOME/usage/quota.jsonl; then the conversion of the ledger's API-price cost
                 into a share of the window, the percent now, at the reset at the last 24 h's pace, what the live
                 sessions have left, how many startable P0/P1 items fit, and the advice (open waves, only P0/P1,
                 none); written to $BRAIN_HOME/usage/quota.json for the cockpit
  brain usage guard [--json]   the usage governor (brain.governor, the PreToolUse hook on start_session, Agent and
                 Workflow): the quota windows it reads, the sessions running and the brainstorms open on this
                 machine, the committed memory, the caps (config.json usage.guard, lowered by the project's usage:)
                 and what a new session, a brainstorm, a subagent and a workflow would get now (ask at WARN, refuse at
                 CRITICAL, past a cap or while the newest reading is stale)
  brain usage allow [--hours H] [--reason TEXT]   {owner}'s override of the usage governor for H hours (default 2;
                 0 ends it), run in their own terminal: the guards refuse it to a session
  brain cost estimate ITEM|TEXT|@FILE|- [--class trivial|standard|strategic] [--record] [--json]   cost, output,
                 context peak, active time and sessions (median, p25-p75) from the finished items most alike, times
                 the class's calibration; --record writes props.cost_estimate on the item
  brain cost review [ITEM] [--since WHEN] [--until WHEN] [--record] [--json]   actual against the recorded (else
                 backtest) estimate and the brief's budget, and the token-free signals that explain the gap;
                 --record writes props.cost_review
  brain cost audit [--since WHEN] [--until WHEN] [--top N] [--write] [--json]   the window's estimates off by more
                 than x1.5 and why, the calibration per class, the costliest sessions, the script candidates;
                 --write: <BRAIN_HOME>/usage/<project>/audit-<since>_<until>.md, and the week's forecast snapshot
                 <BRAIN_HOME>/forecast/<project>/<day>.json (the Monday task's command)
  brain forecast [--project P | --all] [--runs N] [--seed S] [--items] [--no-scan] [--json]   when each milestone
                 and the whole backlog will be done: a Monte Carlo of futures (a shared estimate error from the
                 backtests, a lognormal per item from its p25-p75, the capacity of past days, the proposals' keep rate,
                 the owner's answer delays, an event-queue scheduler by priority, order, then the default score), p10-p90
                 under the honesty bar: uncalibrated until 5 reached milestones are judged, no date beyond 6 weeks,
                 none for a backlog that grows faster than it empties, the deferred items and the inflow apart; --items
                 per item p10 . p50 . p80 . p90; --json reproducible (seed, input digests, code version); every run
                 keeps <BRAIN_HOME>/forecast/<project>/latest.json (brain status --quick reads it)
  brain tui [--project P | --all] [--refresh 2s] [--probe 5m] [--hours 24] [--plain] [--sort PANEL:KEY]...
            [--filter PANEL:FIELD=VALUE]... [--search TEXT] [--tz local|utc] [--reset] [--once [--quick]] [--json]
                 the cockpit, read-only and at zero token: sessions (project, task, step n/m of its plan, state,
                 model, effort, context and tokens), {owner}'s queue, alerts, milestones, the frontier by priority,
                 audit debt, stacks and code index, the digest; the panels re-read when their files change (checked
                 every --refresh, default 2 s; + and - change it), the probes (alerts, audit, health, digest, denied
                 calls) every --probe and on the r key; the Textual app with the tui extra (pip install brain[tui]),
                 else (--plain) the same text redrawn in place; --once prints it once (--quick: no probe), --json its
                 data (unfiltered). The project selector (p: global or one project), the sessions', queue's and
                 frontier's filters and sorts (f, s, o), the search (/), a panel's help (i) and full view (m, Escape
                 back), the pause (space) and ? for every key; a refresh keeps the scroll and the cursor; the
                 interactive views remember the scope, views, theme and timezone (--tz, t; default local) in
                 $BRAIN_HOME/tui.json (--reset forgets them; --project, --all, --sort, --filter and --tz win).
                 Enter: the row's detail (a DDR's options, an item's spec, ADRs and PR, a session's plan); in it, o
                 opens a link in the editor or the browser, a answers a decision, d marks an action or a permission
                 done, A applies an action's command, each run as {owner}'s after a confirmation of the exact brain
                 command and logged in $BRAIN_HOME/ledger/cockpit-<month>.jsonl (refused in a Claude Code session).
                 The title bar: the installed version, « pin v0.2.3: -Apply » when it lags config.json engine.pin and
                 the brain declares its installer (engine.installer), « 0.2.4 available » for a newer tag; u then
                 shows that installer's plan (else brain update's) and, on y, the cockpit exits and a new window
                 installs (-Apply, or brain update --yes) and relaunches brain tui with the same arguments
  brain tui --detail ID [--quick] [--json]   one row's detail printed: a DDR, an item, a milestone, a session (the
                 start of its id), an alert's key; its links and its actions with their exact commands

The repo acted on is --root, else the registered project --project NAME (projects.yaml of the Brain repo), else
$BRAIN_ROOT, else the nearest folder above with notes/graph/schema.yaml (a worktree of a registered project keeps its
name). --project with --root: that project's layout at that root (a worktree). --project goes before or after the
subcommand. Every view takes --project NAME or --all (every registered project), not both: status, projects, resume,
digest, queue, decision pending, batch and view, milestone suggest, spec activate, notify status, alerts, lint rules,
audit, sync, check, refresh, tui, usage, forecast (cost takes --project);
health, index, up and down take --project to narrow them to that project's stacks and repos (their names are global);
perf reads every project unless --project; timed and memory are machine-wide. A text value written @FILE is read from
FILE; a journal line '-' reads stdin.
The local ledger the hooks write is $BRAIN_HOME (default ~/.brain). The stacks are declared under each project's
stacks: in projects.yaml (brain.stacks); up, down and health print one line per stack, exit 1 on a failure. The repos
GitNexus indexes are declared under each project's code_index:, the stack that indexes them under its index:
(brain.codeindex). The notification channels and each project's routes per level are declared under notify:
(brain.notify); a secret is named by its environment variable only, and $BRAIN_NOTIFY=off sends nothing. Where
each project's alerts come from (scheduler folders, tasks and their cadences, stacks, alert files, event folders,
levels) is declared under alerts: (brain.alerts).
{owner}: config.json's identity.owner (brain config), filled in by build_parser.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import (__version__, actions, alerts, audit, backfill, batch, boundary, bundles, capture, cockpit, codeindex,
               config, cost, decisions, detail, digest, features, forecast, graph, init, links, lint, memory,
               milestones, neutral, notes, notify, paths, perf, permissions, probe, projects, public, queue, quota,
               records, render, resume, specs, stacks, status, tidy, tiers, timing, transcript, update, usage)
from . import answers, classes, defaults, governor, keystore, markers, selftime, vault
from . import skew
from .inventory import AuditError


def _now() -> str:
    return transcript.iso(datetime.now(timezone.utc))


def _text(value: str | None) -> str:
    """A text option: @FILE reads the file, '-' reads stdin, else the value itself."""
    if not value:
        return value or ""
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@") and Path(value[1:]).is_file():
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"brain: {p!r}: expected key=value")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def _transcript_for(args) -> Path:
    if getattr(args, "transcript", None):
        return Path(args.transcript)
    if not getattr(args, "session", None):
        raise SystemExit("brain: give --session ID or --transcript PATH")
    t = paths.find_transcript(args.session)
    if not t:
        raise SystemExit(f"brain: no transcript for session {args.session} under {paths.projects_dir()}")
    return t


# --- record ---

def cmd_record_sr(args, root: Path) -> int:
    path = _transcript_for(args)
    main_stats, subs, n_subs = transcript.session_stats(path)
    sid = main_stats.session_id or path.stem
    ar_ids = [r["id"] for r in records.ledger_records("ar", sid)]
    ar_ids += [a["id"] for _, a in records.load(root)["ar"] if a["session"]["id"] == sid]
    ddr_ids = [r["id"] for r in records.ledger_records("ddr", sid)]
    items = list(args.item or [])
    for r in records.ledger_records("ar", sid):
        items += [i for i in r.get("items", []) if i not in items]
    sr = main_stats.record(path, status="closed" if args.closed else "open", summary=args.summary or "",
                           extra_items=items, actions=ar_ids, ddrs=ddr_ids, subagents=subs, subagent_count=n_subs)
    if args.dry_run:
        print(records._dump_yaml(records.validate("sr", sr)))
        return 0
    out = records.write(root, "sr", sr, replace=args.replace)
    print(f"wrote {out.relative_to(root).as_posix()}")
    return 0


def cmd_record_ar(args, root: Path) -> int:
    if args.import_:
        counts = records.import_ledger(root, ("ar",), args.session or "", args.since or "")
        print(f"imported {counts['ar']} AR(s) from {paths.ledger_dir()}")
        return 0
    if args.from_transcript or (args.session and not args.kind):
        path = _transcript_for(argparse.Namespace(transcript=args.from_transcript, session=args.session))
        found = actions.from_transcript(path)
        n = 0
        for ar in found:
            if args.dry_run:
                print(ar)
            elif records.write(root, "ar", ar) is not None:
                n += 1
        print(f"{len(found)} AR(s) found in {path.name}, {n} written")
        return 0
    if not args.kind:
        raise SystemExit("brain: give --import, --from-transcript PATH, or --kind with its fields")
    at = args.at or _now()
    meta = {"session_id": args.session or "unknown", "tool": args.tool, "model": args.model, "effort": args.effort,
            "version": args.version}
    fields = {"repo": args.repo, "branch": args.branch, "sha": args.sha, "subject": args.subject,
              "items": args.item or []}
    if args.kind == "pr":
        fields["pr"] = {k: v for k, v in {"number": args.pr, "url": args.url, "action": args.action}.items() if v}
    if args.kind == "adr":
        fields["adr"] = {"id": args.adr}
    if args.kind == "ddr":
        fields["ddr"] = args.ddr
    if args.kind == "tag":
        fields["tag"] = args.tag
    key = args.key or args.sha or args.adr or args.ddr or (f"{args.repo}-{args.pr}" if args.pr else at[11:19])
    ar = actions.make_ar(args.kind, f"{actions.slug(str(key), 48)}", at, meta, "cli", **fields)
    if args.dry_run:
        print(records.validate("ar", ar))
        return 0
    out = records.write(root, "ar", ar)
    print(f"wrote {ar['id']} to {out.relative_to(root).as_posix()}" if out else f"{ar['id']} already recorded")
    return 0


def cmd_record_backfill(args, root: Path) -> int:
    report = backfill.run(root, since=args.since or "", until=args.until or "", quiet_hours=args.quiet_hours,
                          subagents=not args.no_subagents, ledger=not args.no_ledger, update=args.update,
                          dry_run=args.dry_run)
    print(backfill.format_report(report, args.dry_run))
    return 0


_parse_option = decisions.parse_option


def cmd_record_ddr(args, root: Path) -> int:
    yaml = graph._yaml()
    if args.import_:
        counts = records.import_ledger(root, ("ddr",), args.session or "", args.since or "")
        print(f"imported {counts['ddr']} DDR(s) from {paths.ledger_dir()}")
        return 0
    now = args.at or _now()
    if args.id:  # stamp an existing DDR: answer, read, applied, archived
        f = root / records.RECORDS_DIR / "ddr" / f"{args.id}.yaml"
        if not f.exists():
            raise SystemExit(f"brain: no {f.relative_to(root).as_posix()}")
        ddr = yaml.safe_load(f.read_text(encoding="utf-8"))
        if args.answer or args.other:
            ddr["answer"] = {"at": now, "by": args.by, "via": args.via}
            if args.answer:
                ddr["answer"]["choices"] = args.answer
            if args.other:
                ddr["answer"]["other"] = args.other
            ddr["status"] = "answered"
        if args.read:
            ddr["read"] = {"at": now, "session": args.session or "unknown"}
        if args.applied:
            ddr["applied"] = {"at": now, "session": args.session or "unknown", "in": args.applied}
            ddr.setdefault("read", {"at": now, "session": args.session or "unknown"})
            ddr["status"] = "integrated"
        if args.archive:
            ddr["archived"] = {"at": now, "session": args.session or "unknown"}
            ddr["status"] = "archived"
        out = records.write(root, "ddr", ddr, replace=True)
        print(f"updated {out.relative_to(root).as_posix()} ({ddr['status']})")
        return 0
    if args.file:
        ddr = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    else:
        if not (args.title and args.question and args.option):
            raise SystemExit("brain: a new DDR needs --title, --question and 2 to 4 --option (recommended first)")
        options = [_parse_option(o) for o in args.option]
        ddr = {"v": 1, "id": f"ddr-{now[:10]}-{actions.slug(args.slug or args.title, 48)}", "title": args.title,
               "question": args.question}
        if args.context:
            ddr["context"] = args.context
        if args.blocks:
            ddr["blocks"] = args.blocks
        ddr.update({"options": options, "recommendation": {"option": options[0]["label"], "why": args.why or ""},
                    "multi_select": args.multi, "other_allowed": True, "blocking": args.blocking,
                    "status": "pending", "asked": {"at": now, "by": args.session or "unknown", "via": "cli"}})
        links = {k: v for k, v in {"adrs": args.adr, "items": args.about_item, "specs": args.spec}.items() if v}
        if links:
            ddr["links"] = links
    if args.dry_run:
        print(records._dump_yaml(records.validate("ddr", ddr)))
        return 0
    out = records.write(root, "ddr", ddr, replace=args.replace)
    print(f"wrote {out.relative_to(root).as_posix()}")
    return 0


def cmd_record_check(args, root: Path) -> int:
    errors, warnings = records.check(root)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    counts = {k: len(v) for k, v in records.load(root).items()}
    print(f"records: {counts['ddr']} DDR, {counts['sr']} SR, {counts['ar']} AR; "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def cmd_record_sync(args, root: Path) -> int:
    n, e, left = records.write_graph(root, _store(args, root))
    print(f"records graph: {n} node(s), {e} edge(s)" + (f", {left} link(s) to nodes not in the store" if left else ""))
    return 0


# --- item ---

def _project(args, root: Path) -> projects.Project:
    """--project's, else the registered project at ``root`` (a worktree of its checkout keeps its name)."""
    return getattr(args, "project_obj", None) or resume.project_for(root)


def _store(args, root: Path) -> Path:
    if getattr(args, "store", None):
        return Path(args.store).resolve()
    stores = _project(args, root).stores
    return stores[0] if stores else root / "notes" / "graph"


def cmd_item(args, root: Path) -> int:
    store = _store(args, root)
    try:
        if args.item_cmd == "add":
            props = {k: v for k, v in {"priority": args.priority, "priority_reason": args.reason, "theme": args.theme,
                                       "idea": args.idea}.items() if v}
            props.update(_kv(args.prop))
            node = graph.add_item(store, args.id, args.title, node_type=args.type, status=args.status, props=props,
                                  spec=args.spec, after=args.after, milestone=args.milestone, adr=args.adr,
                                  anchor=args.anchor, file=args.file, edges_file=args.edges_file)
        elif args.item_cmd == "set":
            node = graph.set_item(store, args.id, args.assign)
        elif args.item_cmd == "unlink":
            edge, f = graph.unlink(store, args.id, args.to)
            print(f"unlink: {edge['from']} -{edge['type']}-> {edge['to']} removed from {f.name}; then brain sync and "
                  "brain check")
            return 0
        elif args.item_cmd == "link":
            edge = graph.link(store, args.id, args.type, args.to, args.edges_file, props=_kv(args.prop))
            print(f"link: {edge['from']} -{edge['type']}-> {edge['to']}; then brain sync and brain check")
            return 0
        else:
            node = graph.close_item(store, args.id, args.pr, args.outcome or "", status=args.status)
    except graph.GraphError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"{args.item_cmd}: {node['id']} [{node['status']}]; then brain sync and brain check")
    if args.item_cmd == "add" and args.type == "WorkItem" and not args.milestone \
            and milestones.PROPOSED not in (node.get("props") or {}):
        _print_suggestion(store, node["id"])
    return 0


def _print_suggestion(store: Path, nid: str) -> None:
    """The milestone the signals suggest for a new item (ADR 2026-11-01: proposed, never attached alone)."""
    ix = milestones.index(store)
    if not ix.milestones:
        return
    s = ix.suggest(nid)
    if s:
        print(f"milestone: none; suggested {s.milestone}? ({s.reason}); keep it as a proposal: brain milestone "
              f"suggest --write --only {nid}")
    else:
        print("milestone: none, and no signal suggests one; brain milestone add when no milestone fits")


# --- milestone ---

def _ids(values: list[str] | None) -> list[str] | None:
    """Repeatable ids, each value possibly a comma-separated list."""
    if values is None:
        return None
    return [v.strip() for x in values for v in x.split(",") if v.strip()]


def cmd_milestone(args, root: Path) -> int:
    if args.milestone_cmd == "suggest" and args.all:
        if args.write:
            raise SystemExit("brain: milestone suggest --write takes one project")
        for p in _scope(args, root):
            for store in (s for s in p.stores if (s / "schema.yaml").is_file()) if p.root.is_dir() else ():
                print(f"== {p.name}: {store}")
                _milestone_suggest(args, p.root, store)
        return 0
    store = _store(args, root)
    try:
        if args.milestone_cmd == "suggest":
            return _milestone_suggest(args, root, store)
        if args.milestone_cmd == "apply":
            changes = milestones.apply(store, only=_ids(args.only), skip=_ids(args.skip), overrides=_kv(args.set),
                                       write=args.write)
            for c in changes:
                print(c.line())
            done = " written; then brain sync and brain check" if args.write else \
                f" (not written: --write once {config.name_of()} has validated)"
            print(f"apply: {len(changes)} change(s)" + (done if changes else ""))
            left = milestones.waiting(store)
            if left:
                print(f"left as proposals (milestone not created yet: brain milestone add): {', '.join(left)}")
            return 0
        return _milestone_add(args, root, store)
    except (graph.GraphError, decisions.QueueError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1


def _milestone_suggest(args, root: Path, store: Path) -> int:
    rows = milestones.suggest(store, _ids(args.only), write=args.write)
    notes_: dict[str, str] = {}
    for r in rows:
        if r.proposed and not r.exists and r.proposed not in notes_:
            notes_[r.proposed] = milestones.ddr_note(root, r.proposed)
        print(r.line(notes_.get(r.proposed, "")))
    new = sum(1 for r in rows if not r.proposed and r.suggestion)
    tail = (f" written; then brain sync and brain check, and {config.name_of()} validates (brain milestone apply)"
            if args.write else " (not written: --write)") if new else ""
    print(f"suggest: {len(rows)} open item(s) attached to no milestone, {sum(1 for r in rows if r.proposed)} "
          f"proposed already, {new} new suggestion(s){tail}")
    return 0


def _milestone_add(args, root: Path, store: Path) -> int:
    mid, items = args.id, _ids(args.item) or []
    ddr = decisions.find(root, args.ddr)[1] if args.ddr else milestones.milestone_ddr(root, mid)
    if ddr is None:
        known = graph.node_index(store)
        if mid in known:
            raise graph.GraphError(f"{mid}: already in the graph ({known[mid][1].get('type')}); attach items with "
                                   f"brain milestone apply --set ID={mid}")
        if not args.why:
            raise graph.GraphError(f"a new milestone is put to {config.name_of()} first: give --why (the reason to "
                                   "create it)")
        ddr, kept = milestones.ask(root, store, mid, title=args.title, trigger=_text(args.trigger), items=items,
                                   why=_text(args.why), at=args.at or _now(), parent=args.parent or "",
                                   options=args.option, context=_text(args.context),
                                   project=_project(args, root).name, session=args.session or "")
        print(f"asked {ddr['id']}; {config.name_of()} answers: brain decision answer {ddr['id']} <option>; once the "
              f"creation is chosen, run this command again")
        if kept:
            print(f"brain: warning: other proposals kept: {', '.join(kept)}")
        _queue_changed(root, args)
        return 0
    try:
        changes = milestones.create(root, store, mid, ddr, title=args.title, trigger=_text(args.trigger),
                                    items=items, parent=args.parent or "")
    except milestones.Pending as exc:
        print(f"brain: {exc}", file=sys.stderr if exc.answered else sys.stdout)
        return 1 if exc.answered else 0
    for c in changes:
        print(c.line())
    print(f"add: {mid} in the graph, {len(changes)} item(s) part of it; then brain decision ack {ddr['id']} "
          f"--applied {mid} (once answered), brain sync and brain check")
    return 0


def cmd_spec(args, root: Path) -> int:
    """``brain spec activate``: each proposed spec, ready or what keeps it proposed (brain.specs); --write turns the
    ready ones active, as brain sync and brain refresh do."""
    if args.all and args.write:
        raise SystemExit("brain: spec activate --write takes one project")
    out, rc = [], 0
    for p in _scope(args, root):
        stores = [s for s in (p.stores or [p.root / "notes" / "graph"]) if (s / "schema.yaml").is_file()] \
            if p.root.is_dir() else []
        for store in stores:
            rows = specs.readiness(p.root, store, full=True)
            if args.json:
                out.append({"project": p.name, "store": str(store), "specs": [r.as_dict() for r in rows]})
                continue
            if args.all:
                print(f"== {p.name}: {store}")
            written = []
            if args.write:
                try:
                    written = specs.activate(store, rows, via="brain spec activate")
                except graph.GraphError as exc:
                    print(f"brain: {exc}", file=sys.stderr)
                    rc = 1
            print("\n".join(specs.render(rows, written=bool(written))))
            if written:
                print("then brain sync and brain check")
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return rc


# --- features ---

def _repos(args, root: Path) -> list[projects.Repo]:
    try:
        return projects.repos_of(_project(args, root))
    except projects.RepoError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return []


def _root_repo(args, root: Path) -> str:
    """The name of the repo at the project's root (the one that holds the store): a feature's default repo."""
    for c in _repos(args, root):
        if c.path.resolve() == root.resolve():
            return c.name
    return projects._repo_folder(root).lower()


def _features_view(args, root: Path, store: Path, write: bool, repo: str = "", out: str = "") -> int:
    """FEATURES.md of ``repo`` (default: the root's), written to the root (or ``out``) with ``write``, else checked:
    exit 1 when the file is not the render."""
    repo = (repo or _root_repo(args, root)).lower()
    if repo != _root_repo(args, root) and not out:
        print(f"brain: {repo} is not the repo at {root}: give --out <a worktree of {repo}>/{features.VIEW}",
              file=sys.stderr)
        return 1
    target = Path(out).resolve() if out else root / features.VIEW
    label = store.relative_to(root).as_posix() if store.is_relative_to(root) else store.as_posix()
    text = features.render(features.load_store(store, _root_repo(args, root)), repo, label)
    old = target.read_text(encoding="utf-8") if target.is_file() else None
    if not write:
        why = features.check_view(old, text)
        print(f"{features.VIEW} of {repo}: " + (f"{why}: brain features render --write" if why else "up to date"))
        return 1 if why else 0
    if old is not None and old.replace("\r\n", "\n") == text:
        print(f"view: {features.VIEW} unchanged")
        return 0
    if old is not None and features.MARKER not in old:
        print(f"brain: {target} exists and is not generated (no '{features.MARKER}'): not overwritten",
              file=sys.stderr)
        return 1
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"view: {features.VIEW} written ({repo})")
    return 0


def _features_sync(args, root: Path, store: Path) -> int:
    """brain sync's feature step: the merged PRs' statuses (unless --offline), then FEATURES.md."""
    if not getattr(args, "offline", False):
        features.sync_prs(store, [(c.name, c.path) for c in _repos(args, root) if c.path.is_dir()])
    return _features_view(args, root, store, write=True)


def cmd_features(args, root: Path) -> int:
    store = _store(args, root)
    sub = args.features_cmd
    try:
        if sub in ("list", "search", "show"):
            db = features.open_index(store, _project(args, root).name, _root_repo(args, root))
            try:
                if sub == "list":
                    features.print_list(features.query_list(db, args.status or "", args.domain or "", args.repo or "",
                                                            args.module or "", args.value or ""), args.json)
                elif sub == "search":
                    rows = features.query_search(db, " ".join(args.text), args.limit)
                    features.print_list(rows, args.json) if rows or args.json else print("no feature matches")
                else:
                    f = features.query_show(db, args.id)
                    if f is None:
                        print(f"brain: {args.id}: unknown feature", file=sys.stderr)
                        return 1
                    features.print_show(f, args.json)
            finally:
                db.close()
            return 0
        if sub == "render":
            if args.write and not args.out and _on_main(root):
                raise SystemExit(f"brain: {root} is a main checkout on {_on_main(root)}: render from a worktree")
            return _features_view(args, root, store, args.write, args.repo or "", args.out or "")
        if sub == "sync":
            return _features_sync(args, root, store)
        if sub == "set":
            node = features.set_feature(store, args.id, args.assign)
        else:
            links = {"code": args.code or [], "tests": args.test or [], "docs": args.doc or [],
                     "specs": args.spec or [], "adrs": args.adr or [], "parent": args.parent or "",
                     "items": args.item or []}
            if sub == "link":
                new = features.link(store, args.id, **links)
                print(f"link: {args.id}: {len(new)} edge(s) added; then brain sync")
                return 0
            node = features.add(store, args.id, args.title, args.domain, args.repo or _root_repo(args, root),
                                status=args.status, value=args.value, module=args.module or "",
                                props=_kv(args.prop), **links)
    except (features.FeatureError, graph.GraphError, ValueError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"{sub}: {node['id']} [{node['status']}]; then brain sync (FEATURES.md) and brain check")
    return 0


# --- journal / adr ---

def cmd_journal(args, root: Path) -> int:
    path = Path(args.file).resolve() if args.file else _project(args, root).journal
    lines = [_text(x) for x in args.lines or []]
    try:
        what = notes.journal_add(path, lines, title=args.title or "", day=args.date)
    except notes.NotesError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    print(f"journal: {'new entry' if what == 'entry' else 'lines added'} in {rel} ({args.date or date.today()})")
    return 0


def cmd_adr(args, root: Path) -> int:
    path = Path(args.file).resolve() if args.file else _project(args, root).decisions
    fields = {k: _text(getattr(args, k)) for k in ("context", "decision", "why", "revisit", "why_not_script",
                                                    "trigger", "migration")}
    store = _store(args, root)
    try:
        etypes = graph.load_schema(store).get("edge_types") or []  # before writing: every edge must be possible
        for etype, wanted in (("supersedes", args.reverses), ("decided_by", args.decides)):
            if wanted and etype not in etypes:
                raise graph.GraphError(f"{etype}: not an edge type of {store / 'schema.yaml'}")
        for target in args.decides or []:
            if target not in graph.node_index(store):
                raise graph.GraphError(f"{target}: unknown node (--decides)")
        out = notes.adr_new(path, args.title or "", fields, day=args.date, reverses=args.reverses or "")
        edges = []
        if out["supersedes"]:
            edges.append(graph.link(store, out["id"], "supersedes", out["supersedes"], args.edges_file,
                                    pending={out["id"], out["supersedes"]}, via="brain adr new"))
        for target in args.decides or []:
            edges.append(graph.link(store, target, "decided_by", out["id"], args.edges_file, pending={out["id"]},
                                    via="brain adr new"))
    except (notes.NotesError, graph.GraphError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"adr: {out['id']} appended to {path.name}" + (f"; {len(edges)} edge(s)" if edges else "")
          + "; then brain sync and brain check")
    if out["todo"]:
        print(f"brain: warning: fields left TODO: {', '.join(out['todo'])} (fill them before the commit)")
    return 0


# --- decision queue ---

def _queue_changed(root: Path, args) -> None:
    out = decisions.write_view(root, _project(args, root).name)
    print(f"view: {out.relative_to(root).as_posix()}")


def cmd_decision(args, root: Path) -> int:
    sub = args.decision_cmd
    try:
        if sub == "pending":
            return cmd_pending(args, root)
        if sub == "batch":
            return cmd_batch(args, root)
        if sub == "view":
            if args.all:
                if args.write:
                    raise SystemExit("brain: decision view --write takes one project (brain refresh --all writes "
                                     "every project's views)")
                for p in _scope(args, root):
                    print(decisions.view(p.root, p.name) if p.root.is_dir() else f"# {p.name}: {p.root} not found\n",
                          end="")
                return 0
            name = _project(args, root).name
            if args.write:
                _queue_changed(root, args)
            else:
                print(decisions.view(root, name), end="")
            return 0
        now = args.at or _now()
        if sub == "ask":
            ddr, out = decisions.ask(
                root, title=args.title, question=_text(args.question), options=args.option, why=_text(args.why),
                at=now, context=_text(args.context), blocks=args.blocks or "", multi=args.multi,
                blocking=args.blocking, due=args.due or "", recommend=args.recommend or "", items=args.item,
                specs=args.spec, adrs=args.adr, project=_project(args, root).name, session=args.session or "",
                slug=args.slug or "", dry_run=args.dry_run, low_stakes=args.low_stakes)
            if out is None:
                print(records._dump_yaml(ddr), end="")
                if args.blocking and not args.no_notify:
                    print("\n".join(notify.decision(_notify_project(args, root), ddr, dry_run=True)))
                return 0
            print(f"asked {ddr['id']} ({out.relative_to(root).as_posix()}); {config.name_of()} answers: "
                  f"brain decision answer {ddr['id']} <option>")
            if ddr.get("default"):
                print(f"low-stakes: apply {ddr['default']['option']!r} now, provisionally; it is final by default at "
                      f"{ddr['default']['after']} unless {config.name_of()} answers (brain decision defaulted)")
            if args.blocking and not args.no_notify:
                print("\n".join(notify.decision(_notify_project(args, root), ddr)))
        elif sub == "answer" and args.captured:
            return cmd_answer_captured(args, root)
        elif sub == "defaulted":
            return cmd_defaulted(args, root)
        elif sub == "answer" and args.batch:
            if args.id or args.choice or args.other or args.notes:
                raise decisions.QueueError("--batch takes the answers from its JSON: no ID, CHOICE, --other or "
                                           "--notes")
            done = batch.answer_batch(root, _answers(args.batch), by=args.by, via=args.via, at=now,
                                      again=args.again, check=answers.refusal)
            print(f"answered {len(done['answered'])} decision(s) via {args.via} by {args.by}:")
            print("\n".join(f"  {d['id']}: {decisions._answer_text(d)}" for d in done["answered"]))
            if done["skipped"]:
                print(f"left pending (no answer): {', '.join(done['skipped'])}")
            print("the model in charge applies each answer, then brain decision ack ID --applied <where>")
        elif sub == "answer":
            if not args.id:
                raise decisions.QueueError("answer takes a DDR id and a choice, or --batch with the answers")
            ddr = decisions.answer(root, args.id, args.choice, other=_text(args.other), notes=_text(args.notes),
                                   by=args.by, via=args.via, at=now, again=args.again, check=answers.refusal)
            print(f"answered {ddr['id']}: {decisions._answer_text(ddr)}; the model in charge applies it, then "
                  f"brain decision ack {ddr['id']} --applied <where>")
        elif sub == "ack":
            ddr, unknown = decisions.ack(root, args.id, args.applied, session=args.session or "", at=now,
                                         archive=not args.keep, store=_store(args, root))
            print(f"{ddr['status']} {ddr['id']} (applied in {', '.join(args.applied)})")
            if unknown:
                print(f"brain: warning: not in the graph yet: {', '.join(unknown)} (brain sync after the ADR?)")
        else:
            done = decisions.archive(root, args.ids, session=args.session or "", at=now)
            print(f"archived {len(done)}: {', '.join(done) or 'none'}")
    except (decisions.QueueError, batch.BatchError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    _queue_changed(root, args)
    return 0


def _answers(value: str) -> str:
    """--batch: @FILE or a file path (UTF-8 with or without a BOM, or UTF-16), '-' (stdin), else the JSON itself."""
    if value.startswith("@"):
        if not Path(value[1:]).is_file():
            raise batch.BatchError(f"{value[1:]}: no such file")
        return batch.decode(Path(value[1:]).read_bytes())
    if value != "-" and not value.lstrip("\ufeff").lstrip().startswith(("{", "[")) and Path(value).is_file():
        return batch.decode(Path(value).read_bytes())
    if value == "-":
        return batch.decode(sys.stdin.buffer.read()) if hasattr(sys.stdin, "buffer") else sys.stdin.read()
    return value


# --- the answers' lane (brain.answers) and the defaults (brain.defaults) ---

def cmd_answer_captured(args, root: Path) -> int:
    """``brain decision answer --captured``: this session's captured answers, recorded in one PR (brain.answers)."""
    if args.id or args.choice or args.other or args.notes or args.batch:
        raise decisions.QueueError("--captured takes the answers from the capture: no ID, CHOICE, --other, --notes "
                                   "or --batch")
    session = args.session or answers.session_id()
    if answers.agent_session() and not session:
        raise decisions.QueueError("--captured in an agent's session needs its id (CLAUDE_CODE_SESSION_ID)")
    if answers.agent_session() and args.session and args.session != answers.session_id():
        raise decisions.QueueError("an agent's session records only its own captured answers (one writer per batch)")
    project = _project(args, root)
    caps = answers.unrecorded(session, project.name)
    if not caps:
        print(f"no captured answer to record for {project.name}" + (f" (session {session})" if session else ""))
        return 0
    for c in caps:
        print(f"  {c['ddr']} ({c.get('header')}): {c['answer']}" + (f" — notes: {c['notes']}" if c.get("notes")
                                                                     else ""))
    if args.dry_run:
        print(f"dry run: {len(caps)} answer(s) to record in one PR")
        return 0
    try:
        out = answers.record_captured(project, caps, owner=args.by, session=session, merge=not args.no_merge,
                                      retries=args.retries, again=args.again)
    except answers.AnswersError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {len(out['recorded'])} answer(s) on {out['branch']}: {out['pr']}")
    if out["skipped"]:
        print(f"not pending, left: {', '.join(out['skipped'])} (--again replaces an answer)")
    for line in out["log"]:
        print(f"  {line}")
    if not out["merged"]:
        print(f"not merged yet: {out['pr']} (worktree {out['worktree']})")
    else:   # the hooks read the main checkout's queue: the other sessions see the answers once it is pulled
        print(f"merged: once {project.root} is pulled, the hooks announce the answers to every session of the project")
    print("the sessions that own each decision apply it, then brain decision ack ID --applied <where>")
    return 0


def cmd_defaulted(args, root: Path) -> int:
    """``brain decision defaulted``: the review list of the decisions taken by default (brain.defaults)."""
    now = args.at or _now()
    scope = [p for p in _scope(args, root) if (p.root / records.RECORDS_DIR / "ddr").is_dir()]
    if args.seen is not None and answers.agent_session():
        raise decisions.QueueError(f"--seen is {config.name_of()}'s own note that they read the defaults: from their "
                                   "terminal or the cockpit, not an agent's session")
    out = []
    for p in scope:
        if args.apply:
            for ddr_id in defaults.finalize(p.root, now):
                print(f"{p.name}: {ddr_id} taken by default")
        if args.seen is not None:
            done = defaults.seen(p.root, args.seen, at=now, session=args.session or "")
            print(f"{p.name}: reviewed {len(done)}: {', '.join(done) or 'none'}")
        if args.apply or args.seen is not None:
            decisions.write_view(p.root, p.name)
        out.append({"project": p.name, **defaults.review(p.root, now)})
    if args.json:
        print(json.dumps(out if args.all else (out[0] if out else {}), ensure_ascii=False, indent=1))
        return 0
    for d in out:
        print("\n".join(defaults.render(d["project"], d)))
    return 0


def cmd_batch(args, root: Path) -> int:
    """``brain decision batch``: the zen mode, for this project or every registered one."""
    scope = [p for p in _scope(args, root) if p.root.is_dir()]
    data = [batch.build(p, size=args.size, named=args.all) for p in scope]
    for p, d in zip(scope, data):   # the capture hook ties each answer to its DDR by these (brain.answers)
        try:
            answers.remember(p.name, p.root, d["batches"])
        except OSError as exc:
            print(f"brain: warning: the asked questions were not written to the ledger: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(data if args.all else data[0], ensure_ascii=False, indent=1))
        return 0
    shown = [d for d in data if not args.all or d["batches"] or sum(d["rest"].values())]
    for i, d in enumerate(shown):
        print(("\n" if i else "") + "\n".join(batch.zen(d, args.minutes) if args.zen else batch.render(d)))
    if args.all:
        print(f"all: {sum(d['decisions'] for d in data)} decision(s) in {sum(len(d['batches']) for d in data)} "
              f"batch(es) across {sum(1 for d in data if d['batches'])} of {len(data)} project(s)")
    return 0


def _scope(args, root: Path) -> list[projects.Project]:
    """--all: every registered project; else the one --project names or the one at ``root``."""
    if getattr(args, "all", False):
        if getattr(args, "project", None):
            raise SystemExit("brain: --project or --all, not both")
        reg = projects.load(root)
        if not reg:
            raise SystemExit(f"brain: --all needs the project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                             "$CLAUDE_BRAIN_DIR)")
        return list(reg.values())
    return [_project(args, root)]


def cmd_pending(args, root: Path) -> int:
    kinds = tuple(args.kind) if args.kind else decisions.KINDS
    data = [decisions.pending(p, kinds, with_graph=not args.no_graph) for p in _scope(args, root)]
    if args.json:
        print(json.dumps(data if args.all else data[0], ensure_ascii=False, indent=1))
        return 0
    for d in data:
        print("\n".join(decisions.render_pending(d)))
    if len(data) > 1:
        print(f"all: {sum(d['waiting_on_owner'] for d in data)} waiting on {config.name_of()} in "
              f"{sum(1 for d in data if d['waiting_on_owner'])} of {len(data)} project(s), "
              f"{sum(len(d['answered']) for d in data)} answer(s) to integrate")
    return 0


# --- the owner's queue ---

def cmd_queue(args, root: Path) -> int:
    """``brain queue``: the queue of the project (a worktree of a registered checkout keeps its name), or of every
    registered project with --all; ``add`` and ``done``."""
    sub = getattr(args, "queue_cmd", None)
    try:
        if sub == "add":
            ddr, out, note = queue.add(
                root, kind=args.add_kind, title=args.title or "", what=_text(args.what), at=args.at or _now(),
                context=_text(args.context), blocks=args.blocks or "", items=args.item, specs=args.spec,
                blocking=args.blocking, due=args.due or "", minutes=args.minutes, project=_project(args, root).name,
                session=args.session or "", slug=args.slug or "", command=args.command or "", cwd=args.cwd or "",
                dry_run=args.dry_run, guard=args.guard or "")
            if note:
                print(f"brain: {note}", file=sys.stderr)
            if out is None:
                print(records._dump_yaml(ddr), end="")
                return 0
            print(f"queued {ddr['id']} ({ddr['kind']}, {out.relative_to(root).as_posix()}); once done: "
                  f"brain queue done {ddr['id']}")
            _queue_changed(root, args)
            return 0
        if sub == "apply":
            return _queue_apply(args, root)
        if sub == "order":
            print(queue.order(args.id, at=args.at or _now(), position=args.position, band=args.band or "",
                              clear=args.clear, by=args.by))
            return 0
        if sub == "done":
            print(queue.done(root, args.id, at=args.at or _now(), note=_text(args.note), by=args.by))
            if not args.id.startswith(("perm-", "guard-")):
                _queue_changed(root, args)
            return 0
    except queue.QueueError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    reg = projects.load(root)
    if args.all and not reg:
        raise SystemExit(f"brain: --all needs the project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                         "$CLAUDE_BRAIN_DIR)")
    only = None if args.all else (getattr(args, "project_obj", None) or resume.project_for(root))
    data = queue.collect(list(reg.values()), only=only, kinds=tuple(args.kind or queue.KINDS), days=args.days,
                         with_graph=not args.no_graph, transcripts=not args.no_transcripts)
    shown = data if args.all else [d for d in data if d["project"] != queue.OUTSIDE]
    if args.json:
        print(json.dumps(shown if args.all else shown[0], ensure_ascii=False, indent=1))
        return 0
    outside = 0 if args.all else sum(len(d["entries"]) for d in data if d["project"] == queue.OUTSIDE)
    for d in shown:
        print("\n".join(queue.render(d, outside=outside, legend=not args.all, why=args.explain)))
    if args.all:
        print("\n".join(queue.LEGEND))
        total = {k: sum(d["counts"][k] for d in shown) for k in queue.KINDS}
        print(f"all: {sum(total.values())} waiting on {config.name_of()} in "
              f"{sum(1 for d in shown if d['entries'])} of {len(shown)} group(s): {total['decision']} decision(s), "
              f"{total['action']} action(s), "
              f"{total['permission']} permission(s)")
    return 0


def _queue_apply(args, root: Path) -> int:
    """``brain queue apply ID``: the owner's Apply in their terminal, the cockpit's A (brain.detail): the exact
    commands, the plan of an install.ps1 -Apply, their y, then the run, logged as their action; never from a
    session's shell."""
    p = _project(args, root)
    ddr = detail._ddr(p, args.id)
    if ddr is None or ddr.get("status") != "pending":
        print(f"brain: {args.id}: no pending action of that id in {p.root / records.RECORDS_DIR / 'ddr'}",
              file=sys.stderr)
        return 1
    e = {"id": ddr["id"], "kind": decisions.kind_of(ddr), "source": "ddr", "project": p.name,
         "title": ddr.get("title", "")}
    acts = [a for a in detail.queue_actions(e, p, ddr, via="brain queue apply") if a.kind == "apply"]
    if not acts:
        print(f"brain: {ddr['id']} names no command to apply (brain queue add --command, or the command in "
              f"backquotes in its text); do it, then brain queue done {ddr['id']}", file=sys.stderr)
        return 1
    why = detail.refused()
    if why:
        print(f"brain: {why}", file=sys.stderr)
        return 1
    a = acts[0]
    print(f"Apply {a.ref}: {ddr.get('title', '')}\nin {a.cwd}:")
    print("\n".join(f"  $ {detail.shown(s)}" for s in a.steps))
    if a.preview:
        (plan,) = detail.run(detail.Action("plan", "Plan", a.project, a.ref, a.cwd), [a.preview])
        print(f"\nThe plan ({plan['command']}, exit {plan['exit']}):\n{plan['output'] or '(no output)'}\n")
    try:
        yes = input(f"Run as {config.name_of()}, logged as your action? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:  # no terminal to answer: nothing runs
        yes = False
    if not yes:
        print("nothing run")
        return 1
    results = detail.run(a, a.steps)
    for r in results:
        print(f"{'ok' if r['exit'] == 0 else 'failed, exit ' + str(r['exit'])} in {r['seconds']} s: {r['command']}")
        if r["output"]:
            print(r["output"])
    return 0 if len(results) == len(a.steps) and all(r["exit"] == 0 for r in results) else 1


# --- notify ---

def _notify_project(args, root: Path) -> projects.Project:
    """--project, else the registered project at root; a worktree of a registered checkout gets that project's routes
    (a blocking question asked from a worktree of that project is still sent)."""
    return getattr(args, "project_obj", None) or resume.project_for(root)


def cmd_notify(args, root: Path) -> int:
    try:
        if args.notify_cmd == "status":
            for i, p in enumerate(_scope(args, root) if args.all else [_notify_project(args, root)]):
                print(("\n" if i else "") + "\n".join(notify.status(notify.config(p))))
            return 0
        cfg = notify.config(_notify_project(args, root))
        if args.notify_cmd == "setup":
            print("\n".join(notify.setup(cfg, args.target, find_chat=args.find_chat)))
            return 0
        body = _text(args.message)
        if not body.strip():
            raise notify.NotifyError("give the message (MESSAGE, - for stdin or @FILE)")
        msg = notify.Message(cfg.project, args.level, body, args.title or "", args.source or "", args.key or "",
                             args.link or "")
        res = notify.send(cfg, msg, only=args.channel, dry_run=args.dry_run, force=args.force)
    except notify.NotifyError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.to_json(), ensure_ascii=False, indent=1))
    else:
        print("\n".join(res.lines()))
        if res.status == "dry-run":
            print(f"title: {msg.heading()}\n" + "\n".join("  " + x for x in msg.text().splitlines()))
    return res.code


# --- alerts ---

def cmd_alerts(args, root: Path) -> int:
    """``brain alerts``: the open alerts of the project here or --project's, or every one with --all; --notify: the
    pass that sends the changes since the last one through brain notify. raise | resolve: an alert event."""
    if args.alerts_cmd:
        p = getattr(args, "project_obj", None) or resume.project_for(root)
        code = args.code
        if code is not None and code.lstrip("-").isdigit():
            code = int(code)
        try:
            ev = alerts.emit(p.name, args.key, args.level or ("info" if args.alerts_cmd == "resolve" else "warn"),
                             _text(args.message).strip(), state="open" if args.alerts_cmd == "raise" else "resolved",
                             task=args.task or "", source=args.source or "", code=code, link=args.link or "")
        except ValueError as exc:
            print(f"brain: {exc}", file=sys.stderr)
            return 2
        print(f"alert {ev['state']}: {p.name} {ev['key']} ({ev['severity']})")
        return 0
    if args.dry_run and not args.notify:
        raise SystemExit("brain: --dry-run goes with --notify")
    scope = _scope(args, root)
    data = alerts.run(scope, quick=args.quick, root=root)
    sent = alerts.notify_pass(data, {p.name: p for p in scope}, dry_run=args.dry_run) if args.notify else None
    if args.json:
        print(json.dumps({**data, **({"notify": sent} if sent is not None else {})}, ensure_ascii=False, indent=1,
                         sort_keys=True))
    else:
        print("\n".join(alerts.render(data) + (["notify:"] + ["  " + x for x in sent] if sent is not None else [])))
    if args.fail_on:
        worst = max((alerts.RANK[a["level"]] for d in data["projects"] for a in d.get("alerts", [])), default=-1)
        return 1 if worst >= alerts.RANK[args.fail_on] else 0
    return 0


# --- sync / check / refresh ---

def _records_view(root: Path, store: Path) -> bool:
    """The records' graph view applies to a project with records/ and DDR nodes in its schema."""
    return (root / records.RECORDS_DIR).is_dir() and "DDR" in (graph.load_schema(store).get("node_types") or [])


def _links_repo(args, root: Path) -> tuple[str, projects.Repo | None, list[projects.Repo]]:
    """(name, registry entry) of the repo at ``root``, whose store takes the Doc, Test and Workflow links, and the
    project's repos (the others a CodeRef of the store names are derived into it too)."""
    try:
        cfgs = projects.repos_of(_project(args, root))
    except projects.RepoError:
        cfgs = []
    for c in cfgs:
        if c.path.resolve() == root.resolve():
            return c.name, c, cfgs
    return projects._repo_folder(root).lower(), None, cfgs


def _activate_specs(args, root: Path, store: Path) -> int:
    """The proposed specs whose decisions are all taken and applied, with no thinking phase left, turned active
    (brain.specs; before the graph sync: the kanban and the queue view read the statuses)."""
    try:
        for node in specs.activate(store, specs.readiness(root, store), via=f"brain {args.cmd}"):
            print(f"spec {node['id']}: turned active (closed by {node['props']['activated_by']})")
    except graph.GraphError as exc:
        print(f"brain: specs not activated: {exc}", file=sys.stderr)
        return 1
    return 0


def _sync_store(args, root: Path, store: Path) -> int:
    if _activate_specs(args, root, store):
        return 1
    featured = features.has_type(graph.load_schema(store))
    if featured and not getattr(args, "offline", False):   # before the graph sync: it reads the statuses
        features.sync_prs(store, [(c.name, c.path) for c in _repos(args, root) if c.path.is_dir()])
    rc = graph.research_graph(root, store, "sync", "--write")
    if rc:
        return rc
    if _records_view(root, store):
        n, e, left = records.write_graph(root, store)
        print(f"records graph: {n} node(s), {e} edge(s)" + (f", {left} link(s) to nodes not in the store"
                                                             if left else ""))
    if links.applies(store):
        try:
            n, e, missing = links.write(root, store, *_links_repo(args, root))
            print(f"links graph: {n} node(s), {e} edge(s)" + (f"; not on this machine, left out: {', '.join(missing)}"
                                                             if missing else ""))
        except AuditError as exc:
            print(f"brain: links graph not written: {exc}", file=sys.stderr)
            return 1
    if featured and _features_view(args, root, store, write=True):   # after the links: FEATURES.md shows them
        return 1
    if (root / records.RECORDS_DIR / "ddr").is_dir():
        for ddr_id in defaults.finalize(root, _now()):   # 24 h without an answer: the low-stakes default is final
            print(f"{ddr_id}: taken by default (brain decision defaulted)")
        _queue_changed(root, args)
    if neutral.applies(root) and render.main(root, "claude", do_write=True):   # the marketplace from the source
        return 1
    for line in render.keep_current(root, _project(args, root).name, fix=True):   # AGENTS.md and the like, here
        print(line)
    return graph.research_graph(root, store, "kanban", "--write")


def _check_markers(project: projects.Project, root: Path, store: Path) -> int:
    """1 when the store, a journal, a decision log or a record holds a conflict marker (brain.markers;
    wi-brain-guard-conflict-markers): every brain command loads them, and a stale merge's generated views pass the
    graph check."""
    files = [store, *(project.journals or [project.journal]), *(project.decision_logs or [project.decisions]),
             root / records.RECORDS_DIR]
    hits = markers.scan_files([f for f in files if f])
    for hit in hits:
        print(f"error: {hit} holds a conflict marker: finish the merge in that file, then brain refresh")
    return 1 if hits else 0


def _check_store(args, root: Path, store: Path) -> int:
    if _check_markers(_project(args, root), root, store):   # every later step would read a half-merged file
        return 1
    rc = cmd_record_check(args, root) if (root / records.RECORDS_DIR).is_dir() else 0
    if decisions.view_stale(root, _project(args, root).name):
        print(f"warning: {decisions.VIEW} is stale: brain sync (or brain decision view --write)")
    roots: dict[str, Path] = {}   # the other repos' checkouts, where research_graph reads their nodes' anchors
    if links.applies(store):
        name, cfg, cfgs = _links_repo(args, root)
        roots = links.anchor_roots(cfgs, name)
        try:
            for f in links.stale(root, store, name, cfg, cfgs):
                print(f"warning: {f} is stale: brain sync")
        except AuditError as exc:
            print(f"warning: the links graph could not be checked: {exc}")
    for line in milestones.orphan_lines(store, root):
        print(line)
    for line in skew.check_lines(root):   # the running engine against config.json engine.pin
        print(line)
    rc = _check_session_ids(root) or rc   # a DDR's local_ id that matches no session (scale study gap 19)
    for r in specs.readiness(root, store):
        if r.ready:
            print(f"warning: spec {r.id} is ready to turn active (closed by {r.closed_by()}): brain refresh, or "
                  "brain spec activate --write")
    hard = lint.hard_rules(store)
    if hard and hard["edge_type"]:  # the hard-rule ratio; a soft rule is a warning, never an error
        print("\n".join(lint.render_hard(hard)))
    if neutral.applies(root):   # the marketplace is the source's render: a hand edit fails here
        rc = render.main(root, "claude", check=True) or rc
    gate_rc, lines = public.gate(root)   # boundary.yaml: every file has a side, the engine side holds nothing private
    for line in lines:
        print(line)
    rc = gate_rc or rc
    for line in render.keep_current(root, _project(args, root).name, fix=False):   # a stale AGENTS.md: brain sync
        print(f"warning: {line}")
    line = tidy.hygiene(_project(args, root))   # stale worktrees and merged branches: brain tidy
    if line:
        print(line)
    given = [a for n, p in sorted(roots.items()) for a in ("--repo-path", f"{n}={p}")]
    return graph.research_graph(root, store, "check", *given) or rc


def _check_session_ids(root: Path) -> int:
    """1 when a DDR stamped on this machine names an app id (local_) that matches no session (brain.sessions)."""
    if not (root / records.RECORDS_DIR / "ddr").is_dir():
        return 0
    from . import sessions
    refused, warned = sessions.unknown_ids(decisions.load(root))
    for line in refused:
        print(f"error: {line}")
    for line in warned:
        print(f"warning: {line}")
    return 1 if refused else 0


def cmd_sync(args, root: Path) -> int:
    if skew.refuse(root, "sync", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    if args.all:
        return _each_store(args, root, sync=True, check=False)
    return _sync_store(args, root, _store(args, root))


def cmd_check(args, root: Path) -> int:
    _merge_marks(root, "brain refresh regenerates them")
    if args.all:
        return _each_store(args, root, sync=False, check=True)
    return _check_store(args, root, _store(args, root))


def _merge_marks(root: Path, then: str, clear: bool = False) -> None:
    """The views the merge driver kept from one side in this worktree (brain.mergedriver): said, or cleared once
    brain refresh regenerated them."""
    from . import mergedriver
    views = mergedriver.clear(root) if clear else mergedriver.marked(root)
    if views:
        print(f"merge driver: {len(views)} view(s) kept from one side at the last merge ({', '.join(views)}); {then}")


def check_registry(root: Path | None, projs: list[projects.Project]) -> int:
    """The registry (its keys and shapes, repos, stacks, code_index), its alerts and config.json (brain.config),
    then the ids: unique across every store of every project, unless waived under a project's shared_ids. Exit
    code 1 on an error."""
    errors = projects.check(root) + config.check(root) + permissions.check(root)
    data_classes = classes.check(root)
    for w in data_classes.waived:
        print(f"waived: classes: {w}")
    errors += [f"classes: {e}" for e in data_classes.errors] + [f"vault: {e}" for e in vault.check(root)]
    errors += [f"tiers: {e}" for e in tiers.check(root)]
    errors += [f"alerts: {e}" for e in alerts.check(projects.load(root))]
    for what, load, error in (("stacks", stacks.load, stacks.StackError),
                              ("code_index", codeindex.load, codeindex.CodeIndexError)):
        try:
            load(root)
        except error as exc:
            errors.append(f"{what}: {exc}")
    ids = projects.collisions([p for p in projs if p.root.is_dir()])
    for c in ids["collisions"]:
        line = f"id {c['id']} is in {', '.join(c['where'])}"
        if c["waived"]:
            print(f"waived: {line} (shared_ids of {c['waived']})")
        else:
            errors.append(f"{line} (rename one, or waive it under shared_ids: with its reason)")
    for s in ids["stale"]:
        print(f"warning: shared_ids of {s}: no longer in two stores (remove it)")
    for line in render.registry_warnings(neutral.brain_root(root), projs):
        print(f"warning: {line}")
    for e in errors:
        print(f"error: {e}")
    print(f"registry: {len(projs)} project(s), {ids['stores']} store(s), "
          + (f"{len(errors)} error(s)" if errors else "ids unique"))
    return 1 if errors else 0


def _on_main(root: Path) -> str:
    """The branch when ``root`` is a main checkout on main or master (the checkout services run from), else ''."""
    branch = actions.git(root, "rev-parse", "--abbrev-ref", "HEAD")
    main = paths.main_checkout(root)
    return branch if branch in ("main", "master") and main and main.resolve() == root.resolve() else ""


def cmd_refresh(args, root: Path) -> int:
    """sync --write, the records and queue views, kanban --write, then check, for each store of each project in
    scope. A main checkout on main or master is only checked (its generated files are refreshed from a worktree),
    unless --on-main. --all ends with the registry and the ids (check_registry). Once it passes, the views the merge
    driver kept from one side here are regenerated: their marks are cleared."""
    if skew.refuse(root, "refresh", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    rc = _each_store(args, root, sync=True, check=True)
    if not rc:
        _merge_marks(root, "regenerated", clear=True)
    return rc


def _each_store(args, root: Path, *, sync: bool, check: bool) -> int:
    """sync and/or check each store of each project in scope (refresh, sync --all, check --all); a main checkout on
    main or master is not written unless --on-main; --all with check ends with check_registry."""
    failed = []
    scope = _scope(args, root)
    for p in scope:
        args.project_obj = p
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped")
            continue
        branch = "" if getattr(args, "on_main", False) or not sync else _on_main(p.root)
        for store in p.stores or [p.root / "notes" / "graph"]:
            if not (store / "schema.yaml").is_file():
                print(f"== {p.name}: no store at {store}, skipped")
                continue
            if branch and not check:
                print(f"== {p.name}: {store} (main checkout on {branch}: not written, skipped)")
                continue
            print(f"== {p.name}: {store}" + (f" (main checkout on {branch}: check only)" if branch else ""))
            rc = 0 if branch or not sync else _sync_store(args, p.root, store)
            rc = rc or (_check_store(args, p.root, store) if check else 0)
            if rc:
                failed.append(p.name)
    if check and getattr(args, "all", False):
        print("== registry")
        if check_registry(root, scope):
            failed.append("registry")
    print(f"{args.cmd}: {len(failed)} project(s) failed" + (f": {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def cmd_tidy(args, root: Path) -> int:
    """``brain tidy``: the stale worktrees and merged branches of the project's repos (--all: every registered
    project's), listed, then removed with --apply (brain.tidy)."""
    return tidy.main(_scope(args, root), remote=args.remote, apply=args.apply, as_json=args.json)


def cmd_health(args, root: Path | None, project: str | None) -> int:
    """``brain health``: the stacks asked for (no name: the watched ones, every one with --all, every one of the
    project with --project), then the code index when code-index is named, with --all, or with --project alone, and
    the vault's canaries when vault is named or with --all."""
    names = [n for n in args.stacks if n not in (codeindex.CHECK, vault.CHECK)]
    rc = stacks.main("health", names, args.all, root, project=project) if names or not args.stacks else 0
    if vault.CHECK in args.stacks or args.all:
        rc = max(rc, vault.health(config.load(root), named=vault.CHECK in args.stacks))
    if not (codeindex.CHECK in args.stacks or args.all or (project and not args.stacks)):
        return rc
    try:
        return max(rc, codeindex.health(root, named=codeindex.CHECK in args.stacks, project=project))
    except codeindex.CodeIndexError as exc:
        print(f"brain health: {exc}", file=sys.stderr)
        return 2


# --- status / projects ---

def cmd_status(args, root: Path) -> int:
    """Each project's indicators (brain.status): the project here or --project's, or every one with --all."""
    data = status.run(_scope(args, root), every=args.all, quick=args.quick, root=root)
    print(status.render_json(data) if args.json else "\n".join(status.render(data)))
    return 0


def cmd_tui(args, root: Path) -> int:
    """The cockpit (brain.cockpit): the Textual app with the tui extra, else its text redrawn in place; --once or
    --json: one read. The interactive views start from the scope and the views they last showed
    (<BRAIN_HOME>/tui.json; --project or --all, --sort and --filter win, --reset forgets them) and remember them."""
    try:
        flags = cockpit.parse_view(args.sort, args.filter)
    except ValueError as exc:
        raise SystemExit(f"brain tui: {exc}") from None
    interactive = not (args.once or args.json or args.detail)
    saved = cockpit.load_state() if interactive and not args.reset else {}
    views = {n: {**(saved.get("panels") or {}).get(n, {}), **flags.get(n, {})} for n in cockpit.SORTS}
    settings = {"tz": "local", **(saved.get("settings") or {}), **({"tz": args.tz} if args.tz else {})}
    cp = cockpit.Cockpit(_scope(args, root), every=args.all, root=root, hours=args.hours)
    if not (args.all or getattr(args, "project", None)) and saved.get("scope") in (cockpit.ALL, *cp.choices):
        cp.select(saved["scope"])  # the last scope shown, when it is still registered
    if args.detail:  # the files first; the probes only when the row is not found in them (an alert, a denial)
        cp.refresh(probe=False)
        d = detail.lookup(cp, args.detail)
        if d is None and not args.quick:
            cp.refresh(probe=True)
            d = detail.lookup(cp, args.detail)
        if d is None:
            print(f"brain tui: {args.detail}: no row, DDR, item or milestone of that id in {cp.scope}",
                  file=sys.stderr)
            return 1
        print(detail.as_json(d) if args.json else "\n".join(detail.lines(d)))
        return 0
    if not interactive:
        cp.refresh(probe=not args.quick)
        snap = cp.snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) if args.json
              else "\n".join(cockpit.render(snap, views=views, search=args.search, tz=args.tz)))
        return 0
    cockpit.save_state({"scope": cp.scope, "panels": views, "settings": settings})
    if not args.plain:
        try:
            from . import tui
        except ModuleNotFoundError as exc:
            if (exc.name or "").split(".")[0] not in ("textual", "rich"):
                raise
            print("brain tui: the Textual app needs the tui extra (pip install -e <brain checkout>[tui] in brain's "
                  "venv); the text view meanwhile (Ctrl-C quits)", file=sys.stderr)
        else:
            return tui.run(cp, refresh=args.refresh, probe=args.probe, views=views, search=args.search,
                           settings=settings)
    return cockpit.watch(cp, args.refresh, args.probe, views=views, search=args.search, tz=settings["tz"])


def cmd_update(args, root: Path | None) -> int:
    """brain update (brain.update): the latest tag of the engine's repo read now (the cache refreshed), its CHANGELOG
    and the plan; --check stops there; else installed on the owner's yes (y in a terminal, or --yes), refused in a
    Claude Code session's shell (CLAUDECODE), like the cockpit's actions."""
    return update.main(root, check_only=args.check, yes=args.yes, as_json=args.json, refused=detail.refused())


def _when(text: str | None, default: str = "") -> str:
    try:
        return usage.parse_when(text or default, usage.now_utc())
    except ValueError as exc:
        raise SystemExit(f"brain: {exc}") from None


def cmd_usage(args, root: Path) -> int:
    """The token ledger read back (brain.usage, brain.cost): the project here or --project's sessions, or every one."""
    projs = _scope(args, root)
    if args.rescan:
        usage.update(rescan=True)
    if args.what == "quota":
        return _quota(args, root, projs)
    if args.what in ("guard", "allow"):
        return _governor(args, root)
    led = cost.scoped(cost.load(projs, root, refresh=not (args.no_scan or args.rescan)), projs, args.all)
    by = {"daily": "day", "weekly": "week"}.get(args.report or "", args.by)
    rep = cost.report(led, _when(args.since, "7d"), _when(args.until), by,
                      usage.plans_from(config.load(root).get("usage")))
    print(cost.as_json(rep) if args.json else "\n".join(cost.render_report(rep, args.top)))
    return 0


def _quota(args, root: Path, projs: list[projects.Project]) -> int:
    """brain usage quota (brain.quota): note a reading, then the forecast of the window."""
    now = usage.now_utc()
    try:
        if args.observe is not None:
            rec = quota.observe(args.observe, args.window, quota.parse_time(args.at, now) if args.at else None,
                                quota.parse_time(args.resets, now) if args.resets else None,
                                usage.plans_from(config.load(root).get("usage")))
            if not args.json:
                print(f"noted: {rec['window']} {rec['pct']:g} % at {rec['at']}, resets {rec['resets']} "
                      f"({quota.readings_file()})")
        elif args.at or args.resets:
            raise quota.QuotaError("--at and --resets go with --observe")
        fc = quota.run(cost.load(projs, root, refresh=not (args.no_scan or args.rescan)), projs, now, args.window)
    except quota.QuotaError as exc:
        raise SystemExit(f"brain: {exc}") from None
    print(cost.as_json(fc) if args.json else "\n".join(quota.render(fc)))
    return 0


def _governor(args, root: Path) -> int:
    """brain usage guard | allow (brain.governor): what the usage hook would decide now; the owner's override."""
    if args.what == "allow":
        if args.hours is not None and args.hours < 0:
            raise SystemExit("brain: --hours is 0 or more")
        rec = governor.allow(args.hours if args.hours is not None else governor.ALLOW_HOURS, args.reason or "")
        print(cost.as_json(rec) if args.json else f"usage guard lifted until {rec['until']} ({governor.allow_file()})"
              if rec else "usage guard override ended")
        return 0
    rep = governor.report(str(Path.cwd()))
    print(cost.as_json(rep) if args.json else "\n".join(governor.render(rep)))
    return 0


def cmd_cost(args, root: Path) -> int:
    """brain cost estimate|review|audit (brain.cost): the project here or --project's items and sessions."""
    projs = _scope(args, root)
    led = cost.load(projs, root)
    today = usage.now_utc().date().isoformat()
    if args.cost_cmd == "estimate":
        target = cost.target_of(led, _text(args.target), args.task_class)
        est = cost.estimate(led, target, today)
        if args.record:
            if target.get("id") != args.target.strip():
                raise SystemExit("brain: --record needs an item id as the target")
            cost.record(target.get("store"), target["id"], "cost_estimate", cost.estimate_text(est))
        print(cost.as_json(est) if args.json else "\n".join(cost.render_estimate(est) + (
            [f"recorded on {target['id']} (props.cost_estimate); then brain refresh"] if args.record else [])))
        return 0
    since, until = _when(args.since), _when(args.until)
    if args.cost_cmd == "review":
        if args.item and args.item not in led.items:
            raise SystemExit(f"brain: {args.item}: no such item in {', '.join(p.name for p in projs)}")
        ids = [args.item] if args.item else [a["id"] for a in cost.history(led) if a["done_day"] >= since
                                             and (not until or a["done_day"] < until)]
        reviews = [cost.review(led, i) for i in ids]
        if args.record:
            for rv in reviews:
                cost.record(led.items[rv["item"]["id"]].store, rv["item"]["id"], "cost_review",
                            cost.review_text(rv, today))
        if args.json:
            print(cost.as_json(reviews))
            return 0
        lines = [x for rv in reviews for x in cost.render_review(rv)] or [f"no finished item since {since}"]
        if args.record and reviews:
            lines.append(f"{len(reviews)} review(s) recorded (props.cost_review); then brain refresh")
        print("\n".join(lines))
        return 0
    au = cost.audit(led, since, until, args.top)
    name = projs[0].name if len(projs) == 1 else "all"
    text = cost.render_audit(au, name, usage.now_utc().strftime("%Y-%m-%d %H:%M UTC"))
    out = cost.audit_path(name, since, until)
    snaps = []
    if args.write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        for p in projs:  # the week's forecast snapshot, what the calibration judges (spec-brain-psychohistory 6)
            try:
                snaps.append(str(forecast.save(forecast.forecast(p, led, usage.now_utc()), snapshot=True)))
            except (forecast.ForecastError, OSError, ValueError) as exc:
                snaps.append(f"{p.name}: no forecast snapshot ({exc})")
    print(cost.as_json(au) if args.json else text + (f"\nwritten to {out}" if args.write else "")
          + "".join(f"\nforecast snapshot: {s}" for s in snaps))
    return 0


def cmd_forecast(args, root: Path) -> int:
    """brain forecast (brain.forecast): the project here or --project's, or each project with --all (each alone:
    the joint simulation is wi-brain-scope-rollups'); each run keeps latest.json."""
    if args.runs < 1:
        raise SystemExit("brain forecast: --runs needs one future at least")
    projs = _scope(args, root)
    led = cost.load(projs, root, refresh=not args.no_scan)
    now = usage.now_utc()
    out = []
    for p in projs:
        if not p.root.is_dir():
            continue
        try:
            res = forecast.forecast(p, cost.Ledger(led.rows, [p]) if len(projs) > 1 else led, now, runs=args.runs,
                                    seed=args.seed)
        except forecast.ForecastError as exc:
            print(f"brain forecast {p.name}: {exc}", file=sys.stderr)
            continue
        forecast.save(res)
        out.append(res)
    if args.json:
        print(forecast.as_json(out[0] if len(out) == 1 and not args.all else out))
    else:
        print("\n\n".join("\n".join(forecast.render(res, args.items)) for res in out))
    return 0 if out else 1


def _duration(text: str) -> float:
    """argparse type: 500ms, 2s, 5m, 1h or seconds, at least 0.25 s."""
    try:
        s = cockpit.duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    if s < 0.25:
        raise argparse.ArgumentTypeError(f"{text!r}: 250ms at least")
    return s


def cmd_projects(args, root: Path) -> int:
    """The registry resolved: every project, or --project's; --keys: what an entry may hold."""
    if args.keys:
        for k, text in projects.KEYS.items():
            print("\n".join(status._row(k, text)))
        return 0
    projs = [args.project_obj] if getattr(args, "project_obj", None) else list(projects.load(root).values())
    if not projs:
        raise SystemExit(f"brain: no project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or $CLAUDE_BRAIN_DIR)")
    data = [projects.describe(p) for p in projs]
    if args.json:
        print(json.dumps({"projects": data}, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    for d in data:
        print(f"{d['name']} ({d['root']}" + ("" if d["found"] else ", not found on this machine") + ")"
              + (f": {d['title']}" if d["title"] else ""))
        for key, label in (("stores", "stores"), ("journals", "journals"), ("decisions", "decisions"),
                           ("ledgers", "ledgers"), ("repos", "repos"), ("production", "production"),
                           ("code_index", "code index"), ("stacks", "stacks"), ("shared_ids", "shared ids"),
                           ("plugin", "plugin")):
            value = d[key]
            text = (", ".join(f"{k}: {v}" for k, v in value.items()) if isinstance(value, dict)
                    else ", ".join(map(str, value)) if isinstance(value, list) else str(value or ""))
            print("\n".join(status._row(label, text or "-")))
    return 0


def cmd_config(args, root: Path) -> int:
    """The personal brain's config.json resolved; --keys: what it may hold; --check: exit 1 when it breaks the
    contract (brain.config)."""
    if args.keys:
        for k, text in config.keys():
            print("\n".join(status._row(k, text)))
        return 0
    errors = config.check(root)
    data = config.describe(config.load(root))
    if args.json:
        print(json.dumps({"config": data, "errors": errors}, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print(f"{data['file'] or 'no ' + config.FILE + ' (the defaults)'}: owner {data['owner']} ({data['kind']}"
              + (f", tenant {data['tenant']}" if data["tenant"] else "") + ")")
        engine = data["engine"]
        deny = ", ".join(f"{k} {n}" for k, n in data["deny"].items() if n)
        for label, text in (("registry", data["registry"]), ("rules", ", ".join(data["rules"])),
                            ("memory", data["memory"]), ("records", data["records"]), ("source", data["source"]),
                            ("claude", "{plugin}@{marketplace}".format(**data["claude"])
                             + (f" from {data['claude']['source']}" if data["claude"]["source"] else "")),
                            ("engine", f"{engine['repo']}@{engine['pin']}" if engine else
                             "not pinned (config.json engine: {repo, pin}, the tag the installer installs)"),
                            ("personal", data["personal"] or "no pointer ($BRAIN_PERSONAL, <BRAIN_HOME>/personal.json)"),
                            ("public", ", ".join(data["public_repos"])), ("denied", deny),
                            ("allowed", ", ".join(data["allow"])), ("secrets", ", ".join(data["secrets"]))):
            print("\n".join(status._row(label, text or "-")))
        for e in errors:
            print(f"error: {e}")
    return 1 if args.check and errors else 0


def cmd_profile(args, root: Path) -> int:
    """``brain profile`` (alias ``brain doctor``): this machine's facts, profile, each entry's state and Recommended;
    ``list``, ``show``, ``set`` (the plan; --apply writes $BRAIN_HOME/profile.json) and ``render`` (what install.ps1
    reads) (brain.tiers, brain.probe)."""
    sub = getattr(args, "profile_cmd", None)
    as_json = getattr(args, "json", False)
    if not sub:
        doc = tiers.doctor(root, quick=args.quick)
        print(json.dumps(doc, ensure_ascii=False, indent=1) if as_json else "\n".join(tiers.render_doctor(doc)))
        return 1 if doc["brain"]["profile"]["errors"] else 0
    reg, errors = tiers.registry(root)
    for e in errors:
        print(f"brain profile: {e}", file=sys.stderr)
    ch = tiers.choice(root)
    base = getattr(args, "base", None)
    facts = (probe.facts(probe.collect(quick=True, roots=[root]))
             if sub in ("list", "show") or base == "recommended" else None)
    if sub == "list":
        data = tiers.profiles(reg, ch, facts)
        print(json.dumps(data, ensure_ascii=False, indent=1) if as_json else "\n".join(tiers.render_list(data)))
        return 0
    if sub == "show":
        rows = tiers.show(reg, args.name, ch, facts)
        print(json.dumps(rows, ensure_ascii=False, indent=1) if as_json else
              "\n".join(tiers.render_show(args.name, rows)))
        return 0
    try:
        new = (tiers.plan(reg, ch, base, args.with_ or [], args.without or [], facts)
               if base or args.with_ or args.without else ch)
    except tiers.TierError as exc:
        print(f"brain profile {sub}: {exc}", file=sys.stderr)
        return 2
    if sub == "render":
        print(json.dumps(tiers.render(reg, new), ensure_ascii=False, indent=1))
        return 0
    path, written = (tiers.write(new) if args.apply else (tiers.machine_file(), False))
    print("\n".join(tiers.render_plan(reg, ch, new, args.apply, written, path)))
    return 0


def cmd_boundary(args, root: Path) -> int:
    """Every tracked file's side by boundary.yaml, and the readiness of the engine side (brain.boundary)."""
    return boundary.main(root, check=args.check, side=args.side or "", detail=args.readiness, as_json=args.json)


def cmd_render(args, root: Path) -> int:
    """``brain render``: the neutral source written as an agent's own files (brain.render). The brain is the one with
    the neutral source (--root, the repo here, else config.json's); the project is --project, else the one here."""
    base = neutral.brain_root(Path(args.root).resolve() if args.root else None)
    obj = getattr(args, "project_obj", None)
    if obj is None and args.target != "claude":
        here = projects.for_root(paths.find_root())
        obj = here if here.registered else None
        if obj is None:
            print("brain render: name the project to render for (--project; brain projects lists them)",
                  file=sys.stderr)
            return 2
    project_root = Path(args.repo).resolve() if args.repo else (obj.root if obj else None)
    if args.write and not args.out and skew.refuse(base, "render", args.force):   # another engine than the pin
        return 1
    return render.main(base, args.target, project=obj.name if obj else None, project_root=project_root,
                       out=Path(args.out).resolve() if args.out else None, do_write=args.write, check=args.check,
                       force=args.force, as_json=args.json)

def cmd_classes(args, root: Path) -> int:
    """Every store's data class and where it may go (brain.classes)."""
    return classes.main(root, check_only=args.check, as_json=args.json, which=args.paths, suggest_=args.suggest,
                        matrix_=args.matrix)


def cmd_vault(args, root: Path) -> int:
    """``brain vault``: status, seal, canary, recipient add, device init, open, drill (brain.vault). Open, drill and
    device init are the owner's acts: refused in an agent session. Exit 2 on a refusal."""
    cfg = config.load(root)
    try:
        if args.vault_cmd == "status":
            s = vault.status(cfg)
            print(json.dumps(s, indent=1, sort_keys=True) if args.json else "\n".join(vault.render_status(s)))
            return 1 if s["errors"] else 0
        if args.vault_cmd == "seal":
            man = vault.seal(cfg, args.store, [Path(p) for p in args.paths] or None,
                             Path(args.out) if args.out else None, args.adapter)
            print(f"sealed {man['store']} ({man['class']}, {man['files']} file(s)) to "
                  f"{', '.join(r['name'] for r in man['recipients'])} with {man['adapter']}: "
                  f"{vault.vault_dir() / 'sealed' / man['store'] / man['file'] if not args.out else args.out}")
            return 0
        if args.vault_cmd == "canary":
            res = vault.canary(cfg)
            for name, e in res.items():
                print(f"{name}: " + (f"error: {e['error']}" if e["error"] else
                                     f"sealed ({e['adapter']})" + (", opened by this machine's key"
                                                                   if e.get("opened_at") else "")))
            return 1 if any(e["error"] for e in res.values()) else 0
        if args.vault_cmd == "recipient":
            entry, written = vault.recipient_add(cfg, args.name, args.kind, args.age or "", args.gpg or "",
                                                 args.host or "", args.write)
            print(json.dumps({args.name: entry}))
            print(f"written to {cfg.file}" if written else "plan only: run again with --write to add it")
            return 0
        if args.vault_cmd == "device":
            vault.human_only("brain vault device init")
            facts = vault.device_init(cfg, args.name, args.adapter)
            print(f"device key {facts['name']} ({facts['adapter']}) created in the keystore ({facts['keystore']})")
            print(f"public: {facts['public']}")
            print(f"declare it (a PR): {facts['declare']}")
            return 0
        if args.vault_cmd == "open":
            vault.human_only("brain vault open")
            sealed = Path(args.file)
            out = Path(args.out) if args.out else sealed.with_name(sealed.name.split(".")[0] + ".opened")
            res = vault.open_sealed(cfg, sealed, out, args.identity or "device")
            print(f"opened {sealed.name} into {res['out']} ({res['entries']} entries)")
            return 0
        if args.vault_cmd == "drill":
            vault.human_only("brain vault drill")
            res = vault.drill(cfg, args.recipient, args.identity or "-")
            print(f"{res['recipient']}: its canary opened and matched, drilled at {res['drilled_at']}")
            return 0
    except (vault.VaultError, keystore.KeystoreError) as exc:
        print(f"brain vault {args.vault_cmd}: {exc}", file=sys.stderr)
        return 2
    return 2


# --- permissions ---

def _brain_root(args) -> Path:
    """The Brain checkout acted on (--root, else the one above the current folder): where permissions.yaml is read
    and a grant written, whatever --project names (a worktree's file, not the installed clone's)."""
    return Path(args.root).resolve() if args.root else paths.find_root()


def cmd_permissions(args, root: Path) -> int:
    """``brain permissions``: the effective list of a project on a machine and where each rule comes from; ``check``,
    ``render`` (an adapter's settings files) and ``grant`` (a rule appended in a branch, reviewed by PR)."""
    sub = getattr(args, "permissions_cmd", None)
    base = _brain_root(args)
    try:
        if sub == "grant":
            return _permissions_grant(args, base)
        model = permissions.load(base)
        if sub == "check":
            for e in model.errors:
                print(f"error: {e}")
            print(f"permissions: {model.file or 'no ' + permissions.FILE}, {len(model.rules)} rule(s) with "
                  f"{model.engine_file.name if model.engine_file else 'no ' + permissions.ENGINE_FILE}, "
                  + (f"{len(model.errors)} error(s)" if model.errors else "OK"))
            return 1 if model.errors else 0
        if sub == "render":
            return _permissions_render(args, base, model)
    except permissions.PermissionsError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.requests:
        only = None if args.all else _project(args, root)
        reqs = permissions.select(permissions.requests(model, only=only, days=args.days if args.days != 30 else 7),
                                  status=args.status or "", scope=args.scope or "", item=args.item or "",
                                  search=args.search or "", sort=args.sort)
        if args.json:
            print(json.dumps(reqs, ensure_ascii=False, indent=1))
        else:
            print("\n".join(permissions.requests_text(reqs, title="every project" if args.all else only.name)))
            print("  grant one: brain permissions grant <id> --rule R --why W [level] [--until D | --for-days N | "
                  "--while ITEM]")
        return 0
    scope = list(model.registry) if args.all else [_project(args, root).name]
    out = []
    for i, name in enumerate(scope):
        ctx = permissions.context(model, name, args.machine or "", args.session or "")
        if args.explain:
            text = args.explain
            if text.startswith("perm-"):
                d = permissions.find_denial(text, args.days)
                if d is None:
                    print(f"brain: {text}: no such denial in the last {args.days} days of transcripts", file=sys.stderr)
                    return 1
                text = d["call"]
            data = permissions.explain(model, ctx, text)
            data["proposals"] = permissions.propose(text) if args.explain.startswith("perm-") else []
            out.append(data)
            if not args.json:
                print("\n".join(permissions.explain_text(data)))
                for p in data["proposals"]:
                    print(f"  proposal: {p['rule'] or '-'} for {p['part'][:60]}" + (f" ({p['note']})" if p["note"]
                                                                                    else ""))
            continue
        data = permissions.show(model, ctx)
        if i:   # the user file is the same for every project of this machine
            data["files"] = [f for f in data["files"] if f["scope"] != "user"]
        out.append(data)
        if not args.json:
            print("\n".join(permissions.render_text(data)))
    if args.json:
        print(json.dumps(out if args.all else out[0], ensure_ascii=False, indent=1))
    elif not args.explain:
        print("  brain permissions --explain RULE|perm-ID: where a rule comes from; render: the settings files; "
              "grant: a rule, by PR")
    return 1 if model.errors else 0


def _permissions_render(args, base: Path, model) -> int:
    """render --level user|project|local|session: the plan of each target file; --write adds the missing rules (never
    the user file: install.ps1 -Apply, the owner's); --json for install.ps1 (the user level's rules)."""
    adapter = permissions.ADAPTERS.get(args.target)
    if adapter is None:
        print(f"brain: no adapter for {args.target} yet (built: {', '.join(permissions.ADAPTERS)})", file=sys.stderr)
        return 2
    project = getattr(args, "project_obj", None)
    name = project.name if project else ("" if args.level in ("user", "session") else _project(args, base).name)
    ctx = permissions.context(model, name, args.machine or "", args.session or "")
    if args.level == "session":
        if not args.session:
            print("brain: render --level session needs --session NAME", file=sys.stderr)
            return 2
        if model.errors:
            for e in model.errors:
                print(f"error: {e}")
            print("brain: the hierarchy has errors (brain permissions check): nothing is rendered", file=sys.stderr)
            return 1
        if args.out:
            added = permissions.write_session(model, ctx, Path(args.out))
            print(f"{args.out}: {added} rule(s) added; claude --settings {args.out}")
        else:
            print(json.dumps(permissions.session_settings(model, ctx), ensure_ascii=False, indent=2))
        return 0
    if args.level == "user" and args.json:   # install.ps1's input: every rule of the user scope, by verdict
        want = permissions.wanted(model, ctx, "user", adapter)
        print(json.dumps({"file": str(permissions.claude_home() / "settings.json"), "machine": ctx.machine,
                          **want, "expired": permissions.expired_rules(model, ctx, "user", adapter),
                          "errors": model.errors}, ensure_ascii=False, indent=1))
        return 1 if model.errors else 0
    if args.write and args.level == "user":
        print("brain: install.ps1 -Apply writes the user settings (the owner's); this prints its plan", file=sys.stderr)
        return 1
    plans = permissions.render(model, ctx, args.level, repo=Path(args.repo).resolve() if args.repo else None,
                               write=args.write, adapter=adapter)
    if args.json:
        print(json.dumps(plans, ensure_ascii=False, indent=1))
        return 1 if model.errors else 0
    if not plans:
        print(f"{args.level}: no target (a project level needs a registered project)")
    for p in plans:
        miss = [(v, x) for v in ("allow", "ask", "deny") for x in p["missing"][v]]
        state = "written" if p.get("written") else ("refused: " + p["refused"] if p["refused"] and miss else
                                                    "same" if not miss else "would add")
        print(f"{p['scope']:<7} {p['file']}: {p['present']} of {p['total']} present; {state}")
        for v, x in miss:
            print(f"  {v:<5} {x}")
        for v in ("allow", "ask", "deny"):
            for x in p["unmanaged"][v]:
                print(f"  held, declared by no level: {v} {x}")
    for e in model.errors:
        print(f"error: {e}")
    return 1 if model.errors else 0


def _permissions_grant(args, base: Path) -> int:
    """grant [PERM] [--call C] --rule R --why W: a rule appended to permissions.yaml in this branch; without --rule,
    the narrow rules proposed for the call. A main checkout on main is refused: a grant is reviewed by PR."""
    denial = None
    call = args.call or ""
    if args.perm:
        denial = permissions.find_denial(args.perm, args.days)
        if denial is None and not call:
            print(f"brain: {args.perm}: no such denial in the last {args.days} days of transcripts (--call gives "
                  "the call)", file=sys.stderr)
            return 1
        call = call or denial["call"]
    if not args.rule:
        if not call:
            print("brain: grant needs a permission task (perm-...), --call or --rule", file=sys.stderr)
            return 2
        print(f"{call[:110]}")
        for p in permissions.propose(call):
            print(f"  proposal: {p['rule'] or '-'}  for: {p['part'][:70]}" + (f"  ({p['note']})" if p["note"] else ""))
        print("brain permissions grant ... --rule RULE --why WHY [level]: the rule goes into permissions.yaml")
        return 1
    f = base / permissions.FILE   # this checkout's own file, never one found elsewhere (the main checkout's)
    if not f.is_file():
        print(f"brain: no {permissions.FILE} in {base}: grant writes the file of the checkout it runs in",
              file=sys.stderr)
        return 1
    branch = _on_main(base)
    if branch and not args.dry_run:
        print(f"brain: {base} is the main checkout on {branch}: grant in a worktree's branch, reviewed by PR",
              file=sys.stderr)
        return 1
    selectors = {"project": args.project or "", "machine": args.machine or "", "profile": args.profile or "",
                 "tenant": args.tenant or "", "session": args.session or ""}
    if not any(selectors.values()) and not args.global_:
        if denial is None:
            print("brain: name the level: --global, --project P, --machine H, --profile X, --tenant T or --session S",
                  file=sys.stderr)
            return 2
        place = queue.Placer(list(projects.load(base).values()))
        selectors["project"] = place(denial["cwds"][0]) if denial["cwds"] else ""
        if not selectors["project"]:
            print("brain: the denial ran outside every registered project: name the level", file=sys.stderr)
            return 2
    asked_by, fors = "", []
    if args.perm:   # the request's provenance goes with the rule
        req = next((r for r in permissions.requests(permissions.load(base), days=args.days) if r["id"] == args.perm),
                   None)
        if req:
            asked_by, fors = (req["sessions"] or [""])[0], req["items"] + req["milestones"]
    line, path = permissions.grant(base, rule=args.rule, verdict=args.verdict, selectors=selectors,
                                   until=args.until or "", days=args.for_days or 0, while_=args.while_ or "",
                                   asked_by=asked_by, for_=fors,
                                   why=args.why or "",
                                   by=args.by or "", origin=args.perm or "",
                                   denial=f"{call} {denial['reason'] if denial else ''}".strip(),
                                   dry_run=args.dry_run, path=f)
    print(f"{'would append' if args.dry_run else 'appended'} to {path}:\n{line}")
    if not args.dry_run:
        print("next: commit it in this branch and open the PR (its review is the owner's); once merged, render it "
              "(brain permissions render --level project --write, a production repo through --repo and its own PR; "
              "a user-level rule by install.ps1 -Apply, the owner's)"
              + (f", then brain queue done {args.perm}" if args.perm else ""))
    return 0


# --- resume ---

def cmd_resume(args, root: Path) -> int:
    """The resume pack of the project (a worktree of a registered checkout keeps the project's name), or of every
    registered project with --all; printed, and kept in <BRAIN_HOME>/resume/<project>.md with --write."""
    scope = _scope(args, root) if args.all else [getattr(args, "project_obj", None) or resume.project_for(root)]
    texts = []
    for p in scope:
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped", file=sys.stderr)
            continue
        text = resume.build(p, budget=args.budget, offline=args.offline, health=args.health, notes=args.notes)
        if args.write:
            out = resume.write(p.name, text)
            print(f"resume: {p.name} -> {out} (~{resume.tokens(text)} tokens)", file=sys.stderr)
        texts.append(text)
    print("\n".join(texts), end="")
    return 0


# --- lint ---

def cmd_lint(args, root: Path) -> int:
    """``brain lint rules``: the report for the project of the current folder (a worktree keeps its project's name),
    a registered one, or every one; --propose files the next batch of DDRs in this repo's queue."""
    scope = _scope(args, root) if args.all else [getattr(args, "project_obj", None) or resume.project_for(root)]
    report = lint.lint([p for p in scope if p.root.is_dir()])
    lint.mark_asked(report, root)
    filed = None
    if args.propose:
        filed = lint.propose(root, report, at=args.at or _now(), limit=args.max, session=args.session or "",
                             dry_run=args.dry_run)
        if filed["filed"] and not args.dry_run:
            lint.mark_asked(report, root)
    if args.json:
        out = lint.to_json(report)
        if filed is not None:
            out["proposed"] = filed
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lint.render(report)))
        if filed is not None:
            verb = "would file" if args.dry_run else "filed"
            print(f"propose: {verb} {len(filed['filed'])} DDR(s) ({filed['pending_before']} rules-lint DDR(s) "
                  f"already pending, at most {filed['limit']} at once; {filed['left']} left for a later batch)")
            for f in filed["filed"]:
                print(f"  {f['id']}: {f['title']}")
    if filed and filed["filed"] and not args.dry_run:
        _queue_changed(root, args)
    return 1 if lint.over_cap(report) else 0


# --- digest ---

def cmd_digest(args, root: Path) -> int:
    """The digest of the project (or of every registered project with --all) over a window; printed (the records
    with --json), and kept in <BRAIN_HOME>/digest/<project>/ with --write. A window that does not resolve (a
    milestone not reached, unknown in that project) fails that project only."""
    scope = _scope(args, root) if args.all else [getattr(args, "project_obj", None) or resume.project_for(root)]
    texts, data, rc = [], [], 0
    for p in scope:
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped", file=sys.stderr)
            continue
        try:
            d = digest.gather(p, args.since, args.until, offline=args.offline)
        except digest.DigestError as exc:
            print(f"brain digest: {p.name}: {exc}", file=sys.stderr)
            rc = 1
            continue
        text = digest.render(p, d, budget=args.budget)
        if args.write:
            out = digest.write(p.name, d, text)
            print(f"digest: {p.name} -> {out} (~{resume.tokens(text)} tokens)", file=sys.stderr)
        texts.append(text)
        data.append(d)
    if args.json:
        print(json.dumps(data if args.all else (data[0] if data else None), ensure_ascii=False, indent=1))
    else:
        print("\n".join(texts), end="")
    return rc


# --- the wave's cost: the merge driver, the collisions, the brief (imported when they run) ---

def cmd_merge_driver(args) -> int:
    """brain merge-driver run|install|status|replay (brain.mergedriver)."""
    from . import mergedriver
    if args.merge_cmd == "run":
        return mergedriver.run(args.base, args.ours, args.theirs, args.path,
                               int(args.size) if str(args.size).isdigit() else 7)
    repo = Path(getattr(args, "repo", None) or ".").resolve()
    if args.merge_cmd == "install":
        return mergedriver.install(repo, args.apply, args.launcher, args.json)
    if args.merge_cmd == "status":
        return mergedriver.status(repo, args.json)
    return mergedriver.main_replay(repo, args.since, args.merges, args.json)


def cmd_collisions(args, root: Path) -> int:
    """brain collisions (brain.collisions): the project here or --project's, or --all."""
    from . import collisions
    rep = collisions.report(_scope(args, root), frontier=args.frontier)
    print(json.dumps(rep.as_dict(), indent=2) if args.json else "\n".join(collisions.render(rep)))
    return 0


def cmd_brief(args, root: Path) -> int:
    """brain brief ITEM (brain.brief): the brief printed, and written with --write."""
    from . import brief
    try:
        b = brief.build(_project(args, root), args.item, task_class=args.task_class, budget=args.budget,
                        coordinator=args.coordinator, notes=args.notes)
    except brief.BriefError as exc:
        raise SystemExit(f"brain brief: {exc}") from None
    text = json.dumps(b.as_dict(), indent=2, ensure_ascii=False) if args.json else brief.render(b)
    if args.write:
        Path(args.write).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


# --- coverage (wi-brain-test-coverage; imported when it runs) ---

def cmd_coverage(args, root: Path) -> int:
    """brain coverage (brain.testcov): a repo of the project measured; the summary printed, kept with --write."""
    from . import testcov
    cfgs = _repos(args, root)
    want = (args.repo or _root_repo(args, root) or "").lower()
    c = next((c for c in cfgs if c.name.lower() == want), None)
    if c is None:
        raise SystemExit(f"brain coverage: no repo {want or '?'} in the project (repos: "
                         f"{', '.join(x.name for x in cfgs) or 'none'})")
    try:
        summary, rc = testcov.measure(c, args.run, args.from_data, args.cwd, args.python, args.workers)
    except (testcov.CoverageError, AuditError) as exc:
        raise SystemExit(f"brain coverage: {exc}") from None
    print(testcov.render(summary) if args.json else "\n".join(testcov.lines(summary)), end="" if args.json else "\n")
    if args.write:
        f = _store(args, root) / testcov.FOLDER / f"{c.name.lower()}.json"
        f.parent.mkdir(exist_ok=True)
        f.write_text(testcov.render(summary), encoding="utf-8", newline="\n")
        print(f"brain coverage: wrote {f} (brain sync links the symbols, brain audit reads test.coverage)")
    if rc:
        print("brain coverage: some tests failed; their coverage is counted as run", file=sys.stderr)
    return 0


# --- the session tree (imported when it runs) ---

def cmd_sessions(args) -> int:
    """brain sessions [tree [ID] | show ID] (brain.sessions): machine-wide, no graph store."""
    from . import sessions
    try:
        print(sessions.main(args.sessions_cmd or "list", getattr(args, "ref", "") or "", hours=args.hours,
                            every=args.all, briefs=not args.no_briefs, as_json=args.json,
                            report=getattr(args, "report", False)))
    except sessions.SessionsError as exc:
        raise SystemExit(f"brain sessions: {exc}") from None
    return 0


def build_parser() -> argparse.ArgumentParser:
    who = config.name_of()  # the help names the owner by their display name (identity.display_name)
    by_ = config.owner_of()  # and --by defaults to their id (identity.owner): a record never changes for display
    usage_ = __doc__.replace("{owner}", who).split("\n")
    p = argparse.ArgumentParser(prog="brain", description=usage_[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(usage_[2:-2]))
    p.add_argument("--version", action="version", version=f"brain {__version__}")
    p.add_argument("--root", help="repo to act on (default: $BRAIN_ROOT, else the nearest notes/graph above)")
    p.add_argument("--project", help="a project of the registry (projects.yaml): brain, demo...")
    p.add_argument("--store", help="graph store (default: the project's first store, <root>/notes/graph)")
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="write and validate DDR, SR and AR records").add_subparsers(
        dest="record_kind", required=True)
    sr = rec.add_parser("sr", help="session record from a transcript")
    sr.add_argument("--session")
    sr.add_argument("--transcript")
    sr.add_argument("--summary", help="short summary (default: the session title)")
    sr.add_argument("--item", action="append", help="item touched (repeatable)")
    sr.add_argument("--closed", action="store_true", help="the session is over")
    sr.add_argument("--replace", action="store_true")
    sr.add_argument("--dry-run", action="store_true")

    ar = rec.add_parser("ar", help="action records: import the ledger, recover from a transcript, or one by hand")
    ar.add_argument("--import", dest="import_", action="store_true", help="import the local ledger's ARs")
    ar.add_argument("--from-transcript", help="recover pushes and PRs from a transcript")
    ar.add_argument("--session", help="session id (filter for --import; a transcript to read; the actor)")
    ar.add_argument("--since", help="ISO date or time: import only from then")
    ar.add_argument("--kind", choices=["commit", "push", "pr", "tag", "adr", "ddr"])
    for f in ("repo", "branch", "sha", "subject", "url", "adr", "ddr", "tag", "model", "effort", "version", "at",
              "key"):
        ar.add_argument(f"--{f}")
    ar.add_argument("--pr", type=int)
    ar.add_argument("--action", choices=["created", "merged", "linked", "closed"])
    ar.add_argument("--tool", default="claude-code")
    ar.add_argument("--item", action="append")
    ar.add_argument("--dry-run", action="store_true")

    dd = rec.add_parser("ddr", help="decision discussion record: new, from a file, stamped, or imported")
    dd.add_argument("--import", dest="import_", action="store_true", help="import the question tool's captures")
    dd.add_argument("--file", help="a DDR in YAML to validate and write")
    dd.add_argument("--id", help="an existing DDR to answer or stamp")
    dd.add_argument("--title")
    dd.add_argument("--slug", help="id slug (default: from the title)")
    dd.add_argument("--question")
    dd.add_argument("--context")
    dd.add_argument("--blocks")
    dd.add_argument("--option", action="append", help="'label: consequences', the recommended one first (2 to 4)")
    dd.add_argument("--why", help="reason of the recommendation")
    dd.add_argument("--multi", action="store_true", help="several options can be chosen")
    dd.add_argument("--blocking", action="store_true")
    dd.add_argument("--adr", action="append", help="ADR id the answer went to (repeatable)")
    dd.add_argument("--about-item", action="append", help="WorkItem or Milestone id (repeatable)")
    dd.add_argument("--spec", action="append", help="spec node id or section (repeatable)")
    dd.add_argument("--answer", action="append", help="chosen option label (repeatable)")
    dd.add_argument("--other", help="free-text answer")
    dd.add_argument("--by", default=by_)
    dd.add_argument("--via", default="chat", choices=["ask-tool", "cli", "spec", "chat", "tui"])
    dd.add_argument("--read", action="store_true", help="stamp: the model in charge read the answer")
    dd.add_argument("--applied", action="append", help="stamp: applied in this ADR, item or spec (repeatable)")
    dd.add_argument("--archive", action="store_true")
    dd.add_argument("--session", help="session id of the asker or of the stamp")
    dd.add_argument("--since")
    dd.add_argument("--at", help="time of the question or stamp (default: now)")
    dd.add_argument("--replace", action="store_true")
    dd.add_argument("--dry-run", action="store_true")

    bf = rec.add_parser("backfill", help="SRs and ARs from every transcript on this machine (idempotent)")
    bf.add_argument("--since", help="sessions started from this ISO date or time")
    bf.add_argument("--until", help="sessions started before this ISO date or time (a month: --since 2026-10-01 "
                                    "--until 2026-11-01)")
    bf.add_argument("--quiet-hours", type=float, default=backfill.QUIET_HOURS,
                    help=f"a session is over once its transcript is this old; a younger one gets its ARs, its SR "
                         f"on a later run (default {backfill.QUIET_HOURS})")
    bf.add_argument("--update", action="store_true",
                    help="rewrite an SR whose transcript grew since (its hand-written summary and ids are kept)")
    bf.add_argument("--no-subagents", action="store_true", help="skip the subagents' transcripts")
    bf.add_argument("--no-ledger", action="store_true", help="skip the local ledger's ARs (the hooks' capture)")
    bf.add_argument("--dry-run", action="store_true", help="count what would be written; write nothing")
    rec.add_parser("check", help="validate every record and scan them for secrets")
    rec.add_parser("sync", help="write the records' graph view (nodes/_generated_records.yaml)")

    it = sub.add_parser("item", help="add, set or close a backlog node").add_subparsers(dest="item_cmd", required=True)
    add = it.add_parser("add")
    add.add_argument("id")
    add.add_argument("--title", required=True)
    add.add_argument("--type", default="WorkItem")
    add.add_argument("--status", default="todo")
    add.add_argument("--priority")
    add.add_argument("--reason", help="props.priority_reason: why this priority")
    add.add_argument("--theme")
    add.add_argument("--idea")
    add.add_argument("--spec", help="specified_by edge")
    add.add_argument("--after", action="append", help="depends_on edge (repeatable)")
    add.add_argument("--milestone", help="part_of edge")
    add.add_argument("--adr", help="decided_by edge")
    add.add_argument("--prop", action="append", help="key=value prop (repeatable)")
    add.add_argument("--anchor", default="", help="file#fragment the node points to")
    add.add_argument("--file", default="nodes/work.yaml")
    add.add_argument("--edges-file", default="edges/work.yaml")
    st = it.add_parser("set")
    st.add_argument("id")
    st.add_argument("assign", nargs="+", help="status=doing, title=..., props.<k>=... or <k>=... (empty removes)")
    ln = it.add_parser("link", help="append an edge: brain item link FROM TYPE TO")
    ln.add_argument("id", metavar="from")
    ln.add_argument("type", help="edge type: depends_on, part_of, specified_by, decided_by, delivers...")
    ln.add_argument("to")
    ln.add_argument("--edges-file", default="edges/work.yaml")
    ln.add_argument("--prop", action="append", help="key=value edge prop, e.g. scope=... on enforced_by (repeatable)")
    un = it.add_parser("unlink", help="remove the curated edge between two nodes: brain item unlink FROM TO")
    un.add_argument("id", metavar="from")
    un.add_argument("to")
    cl = it.add_parser("close")
    cl.add_argument("id")
    cl.add_argument("--pr", required=True, help='e.g. "brain #13"')
    cl.add_argument("--outcome", help="one line: what was done and checked")
    cl.add_argument("--status", default="done", choices=["done", "dropped"])

    fe = sub.add_parser("features", help="the feature matrix: Feature nodes, FEATURES.md and a SQLite index with "
                                         "full-text search (brain.features)").add_subparsers(dest="features_cmd",
                                                                                            required=True)
    fl = fe.add_parser("list", help="the features, by domain (filters combine)")
    fl.add_argument("--status", choices=list(features.STATUSES))
    fl.add_argument("--domain")
    fl.add_argument("--repo")
    fl.add_argument("--module", help="a module of the owner's platform (props.module)")
    fl.add_argument("--value", choices=list(features.VALUES))
    fl.add_argument("--json", action="store_true")
    fs = fe.add_parser("search", help="full-text search: every word (a prefix each), best first")
    fs.add_argument("text", nargs="+")
    fs.add_argument("--limit", type=_whole, default=20)
    fs.add_argument("--json", action="store_true")
    fw = fe.add_parser("show", help="one feature: its props and links both ways")
    fw.add_argument("id")
    fw.add_argument("--json", action="store_true")
    fr = fe.add_parser("render", help=f"{features.VIEW}, the matrix by domain: checked, or --write")
    fr.add_argument("--write", action="store_true", help=f"write {features.VIEW} at the root (from a worktree)")
    fr.add_argument("--repo", help="the repo whose features (default: the root's)")
    fr.add_argument("--out", help=f"where to write another repo's {features.VIEW} (its worktree)")
    fy = fe.add_parser("sync", help=f"the statuses named by merged PRs (feat-brain-x: have), then {features.VIEW}")
    fy.add_argument("--offline", action="store_true", help="no gh call: only the render")
    for name in ("add", "link"):
        fp = fe.add_parser(name, help="a new feature and its edges" if name == "add" else
                           "append edges to a feature (an existing pair is skipped)")
        fp.add_argument("id", help="feat-<words>, e.g. feat-brain-records" if name == "add" else "the feature")
        if name == "add":
            fp.add_argument("--title", required=True)
            fp.add_argument("--domain", required=True, help=f"its section of {features.VIEW}")
            fp.add_argument("--status", default="planned", choices=list(features.STATUSES))
            fp.add_argument("--value", default="medium", choices=list(features.VALUES), help="strategic value")
            fp.add_argument("--repo", help="the owner repo (default: the root's)")
            fp.add_argument("--module", help="the platform's module, when known")
            fp.add_argument("--prop", action="append", help="key=value prop (repeatable)")
        fp.add_argument("--code", action="append", help="implemented_by: <path>[::<symbol>] in the feature's repo, "
                                                        "or code:<repo>:<path>[::<symbol>] (CodeRef made if missing)")
        fp.add_argument("--test", action="append", help="tested_by: a Test node")
        fp.add_argument("--doc", action="append", help="documented_in: a Doc node")
        fp.add_argument("--spec", action="append", help="specified_by: a Spec node")
        fp.add_argument("--adr", action="append", help="decided_by: an ADR node")
        fp.add_argument("--parent", help="part_of: the parent Feature")
        fp.add_argument("--item", action="append", help="a WorkItem that delivers it")
    fx = fe.add_parser("set", help="key=value, as brain item set (status have|partial|planned|no checked)")
    fx.add_argument("id")
    fx.add_argument("assign", nargs="+")

    mi = sub.add_parser("milestone", help=f"open items attached to no milestone: proposals, {who}'s validation, new "
                                          "milestones (ADR 2026-11-01: always propose, never attach alone)").\
        add_subparsers(dest="milestone_cmd", required=True)
    ms = mi.add_parser("suggest", help="list the orphans with their proposal, or one from the signals (spec, then "
                                       "depends_on neighbours, then theme); --write stores the new ones")
    ms.add_argument("--only", action="append", help="only these items (repeatable, or comma-separated)")
    ms.add_argument("--write", action="store_true", help="store the new suggestions as props.milestone_proposed "
                                                         "and props.milestone_reason (existing proposals are kept)")
    ms.add_argument("--all", action="store_true", help="every registered project's orphans, printed (not --write)")
    mp = mi.add_parser("apply", help=f"once {who} has validated: write the part_of edges of the proposals, clear "
                                     "them (without --write: the plan)")
    mp.add_argument("--only", action="append", help="only these items (repeatable, or comma-separated)")
    mp.add_argument("--skip", action="append", help="leave these proposals (repeatable, or comma-separated)")
    mp.add_argument("--set", action="append", help=f"ID=MS: {who}'s milestone for an item instead of its proposal, "
                                                   "or for an item without one (repeatable)")
    mp.add_argument("--write", action="store_true", help="write the edges and clear the proposals")
    mn = mi.add_parser("add", help=f"a new milestone through the decision queue: asks {who}, then (same command, "
                                   "once the creation is chosen) writes it and its items' part_of edges")
    mn.add_argument("id", help="the milestone id (ms-...)")
    mn.add_argument("--title", required=True)
    mn.add_argument("--trigger", required=True, help="props.trigger: when the milestone is reached (verifiable)")
    mn.add_argument("--item", action="append", help="work item that goes in it (repeatable, or comma-separated)")
    mn.add_argument("--parent", help="the milestone this one is part of")
    mn.add_argument("--why", help="the reason to create it (the recommendation of the question; first run)")
    mn.add_argument("--option", action="append", help="an alternative 'label: consequences' (up to 3; default: the "
                                                      "best existing milestone for the items, then no milestone)")
    mn.add_argument("--context", help="the question's context (default: the trigger)")
    mn.add_argument("--ddr", help="an existing DDR that asks for this milestone (default: found by its title)")
    mn.add_argument("--session", help="the asking session's id")
    mn.add_argument("--at", help="time asked (default: now)")

    sc = sub.add_parser("spec", help="specs: the proposed ones turn active by themselves once their decisions are "
                                     "taken (brain.specs)").add_subparsers(dest="spec_cmd", required=True)
    sa = sc.add_parser("activate", help="each proposed spec, ready (every DDR naming it answered and acked, no "
                                        "props.open, no unanswered question, no <!-- thinking: open --> marker in "
                                        "its document) or what keeps it proposed; --write turns the ready ones active")
    sa.add_argument("--write", action="store_true", help="turn the ready specs active (status, props.activated and "
                                                         "props.activated_by), as brain sync does")
    sa.add_argument("--all", action="store_true", help="every registered project's proposed specs (not --write)")
    sa.add_argument("--json", action="store_true", help="each store's proposed specs, ready or what they wait on")

    jo = sub.add_parser("journal", help="the project's journal (notes/journal.md), append-only").add_subparsers(
        dest="journal_cmd", required=True)
    ja = jo.add_parser("add", help="a new dated entry (--title), or lines at the end of today's entry")
    ja.add_argument("lines", nargs="*", help="one line each (a bullet unless it is one already); '-' reads stdin, "
                                             "@FILE reads FILE")
    ja.add_argument("--title", help="start a new entry: ## <date> — <title>")
    ja.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ja.add_argument("--file", help="the journal (default: the project's, notes/journal.md)")

    ad = sub.add_parser("adr", help="the project's decision log (notes/decisions.md), append-only").add_subparsers(
        dest="adr_cmd", required=True)
    an = ad.add_parser("new", help="append a dated ADR (Context, Decision, Why, Revisit if; a reversal with "
                                   "--reverses); a missing field is written TODO")
    an.add_argument("title", nargs="?", help="the heading's title (a reversal's default: REVERSAL: <original>)")
    an.add_argument("--context")
    an.add_argument("--decision", help="the decision (a reversal: the new decision)")
    an.add_argument("--why")
    an.add_argument("--revisit", help="Revisit if")
    an.add_argument("--why-not-script", help="for a new or extended rule: why a script cannot do it")
    an.add_argument("--reverses", help="the ADR reversed, by id or title: adds Supersedes and a supersedes edge")
    an.add_argument("--trigger", help="a reversal: what made the old decision wrong")
    an.add_argument("--migration", help="a reversal: what changes, in order")
    an.add_argument("--decides", action="append", help="node decided by this ADR: a decided_by edge (repeatable)")
    an.add_argument("--date", help="YYYY-MM-DD (default: today)")
    an.add_argument("--file", help="the log (default: the project's, notes/decisions.md)")
    an.add_argument("--edges-file", default="edges/work.yaml")

    de = sub.add_parser("decision", help=f"{who}'s decision queue (records/ddr): ask, pending, answer, ack").\
        add_subparsers(dest="decision_cmd", required=True)
    da = de.add_parser("ask", help=f"put a decision to {who}: 2 to 4 options, the recommended one first, its reason")
    da.add_argument("--title", required=True, help="short header (100 characters at most)")
    da.add_argument("--question", required=True)
    da.add_argument("--option", action="append", required=True,
                    help="'label: consequences' ('label:: consequences' when the label has ': '), recommended first")
    da.add_argument("--why", required=True, help="the reason of the recommendation")
    da.add_argument("--recommend", help="the recommended label (checked: it must be the first option)")
    da.add_argument("--context", help="two lines of context")
    da.add_argument("--blocks", help="what waits on the answer")
    da.add_argument("--multi", action="store_true", help="several options can be chosen")
    da.add_argument("--blocking", action="store_true")
    da.add_argument("--due", help="YYYY-MM-DD")
    da.add_argument("--item", action="append", help="WorkItem or Milestone the answer goes to (repeatable)")
    da.add_argument("--spec", action="append", help="spec node or section (repeatable)")
    da.add_argument("--adr", action="append", help="related ADR id (repeatable)")
    da.add_argument("--slug", help="id slug (default: from the title)")
    da.add_argument("--session", help="the asking session's id")
    da.add_argument("--at", help="time asked (default: now)")
    da.add_argument("--dry-run", action="store_true")
    da.add_argument("--no-notify", action="store_true", help="a --blocking question is not sent through the "
                                                             "notification channels (brain notify)")
    da.add_argument("--low-stakes", action="store_true",
                    help="applied at once, provisionally; final by default 24 h later without an answer (brain "
                         "decision defaulted); refused on money, keys, visibility, publication, accounts, arming, "
                         "rules and scheduled tasks")
    dp = de.add_parser("pending", help=f"what waits on {who}: the queue's DDRs, items' props.open, unanswered spec "
                                       f"questions, items blocked on {who}, specs still proposed")
    dp.add_argument("--all", action="store_true", help="every registered project, then the total")
    dp.add_argument("--kind", action="append", choices=list(decisions.KINDS))
    dp.add_argument("--no-graph", action="store_true", help="the DDRs only (no research_graph pending)")
    dp.add_argument("--json", action="store_true")
    dw = de.add_parser("answer", help=f"record {who}'s answer, or a batch of answers (--batch)")
    dw.add_argument("id", nargs="?", help="a DDR id, or a part of it only one DDR has")
    dw.add_argument("choice", nargs="*", help="option label, number (1-based) or start of the label; several when "
                                              "multi_select")
    dw.add_argument("--other", help=f"{who}'s own answer, free text")
    dw.add_argument("--notes")
    dw.add_argument("--by", default=by_)
    dw.add_argument("--via", default="cli", choices=["ask-tool", "cli", "spec", "chat", "tui"])
    dw.add_argument("--again", action="store_true", help="replace an earlier answer")
    dw.add_argument("--batch", metavar="@FILE|-|JSON",
                    help="a session's answers, {id or question: label, labels or {choices, other, notes}}: @FILE, a "
                         "file path, - (stdin) or the JSON itself (brain decision batch prints the questions); "
                         "exact labels, free text only as {\"other\": ...}; a BOM is fine")
    dw.add_argument("--at")
    # the answers' lane (wi-brain-answers-lane): the capture of the question tool, recorded in one PR
    dw.add_argument("--captured", action="store_true",
                    help="record the answers this session's question tool captured, in a worktree and one PR, "
                         "merged with its retries")
    dw.add_argument("--session", help="--captured: the asking session (default: this one, CLAUDE_CODE_SESSION_ID; "
                                      "in the owner's terminal, every session's)")
    dw.add_argument("--no-merge", action="store_true", help="--captured: open the PR, do not merge it")
    dw.add_argument("--retries", type=_whole, default=answers.RETRIES,
                    help=f"--captured: merge attempts after the first (default {answers.RETRIES})")
    dw.add_argument("--dry-run", action="store_true", help="--captured: list what would be recorded")
    # decisions by default (wi-brain-decision-default): the review list
    dd = de.add_parser("defaulted", help=f"the review list: the decisions taken by default, for {who} to take note")
    dd.add_argument("--all", action="store_true", help="every registered project")
    dd.add_argument("--apply", action="store_true", help="record the defaults due now (brain refresh does it too)")
    dd.add_argument("--seen", nargs="*", metavar="ID", help=f"{who} reviewed them (every one listed when no id)")
    dd.add_argument("--session")
    dd.add_argument("--at")
    dd.add_argument("--json", action="store_true")
    db = de.add_parser("batch", help="zen mode: the pending decisions in batches for the question tool, the blocking "
                                     "ones first, then by what they unblock, grouped by brainstorm, item or spec")
    db.add_argument("--all", action="store_true", help="every registered project")
    db.add_argument("--size", type=int, default=batch.SIZE, help=f"questions per batch, 1 to {batch.SIZE} "
                                                                  f"(default {batch.SIZE})")
    db.add_argument("--zen", action="store_true", help="the morning digest: this session's batches in full, then "
                                                       "the rest in a line each")
    db.add_argument("--minutes", type=_whole, default=batch.MINUTES,
                    help=f"--zen: the session's length (default {batch.MINUTES}; 0: every batch)")
    db.add_argument("--json", action="store_true", help="each batch's questions (the question tool's input as is), "
                                                        "ids and entries")
    dk = de.add_parser("ack", help="the model in charge read and applied the answer: integrated, then archived")
    dk.add_argument("id")
    dk.add_argument("--applied", action="append", required=True,
                    help="where it went: an ADR id, an item id, a spec section (repeatable)")
    dk.add_argument("--keep", action="store_true", help="leave it integrated, not archived yet")
    dk.add_argument("--session", help="the acknowledging session's id")
    dk.add_argument("--at")
    dr = de.add_parser("archive", help="archive integrated decisions (all of them when no id is given)")
    dr.add_argument("ids", nargs="*")
    dr.add_argument("--session")
    dr.add_argument("--at")
    dv = de.add_parser("view", help="the generated board notes/decision_queue.md (printed, or --write)")
    dv.add_argument("--write", action="store_true")
    dv.add_argument("--all", action="store_true", help="every registered project's board, printed")
    dn = de.add_parser("announce", help="SessionStart hook: answers not integrated yet (hook JSON on stdin)")
    dn.add_argument("event", nargs="?", default="SessionStart")

    qu = sub.add_parser("queue", help=f"{who}'s queue: decisions, actions only they may do, permissions an agent "
                                      "lacked; in three bands, ranked by what each holds up (--explain)")
    qu.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    qu.add_argument("--all", action="store_true", help="every registered project, then the denials outside them")
    qu.add_argument("--kind", action="append", choices=list(queue.KINDS))
    qu.add_argument("--days", type=int, default=queue.DAYS,
                    help=f"how far back the denied tool calls are read (default {queue.DAYS})")
    qu.add_argument("--no-graph", action="store_true", help="no research_graph pending: no spec questions")
    qu.add_argument("--no-transcripts", action="store_true", help="no transcript scan: no denied tool calls")
    qu.add_argument("--json", action="store_true", help="the data the TUI's panel reads, each entry with its how, "
                                                        "band, score terms and the items it unblocks")
    qu.add_argument("--explain", action="store_true", help="each entry's score, term by term, and why its band")
    qs = qu.add_subparsers(dest="queue_cmd")
    qa = qs.add_parser("add", help=f"put an action or a permission to {who}: a DDR of that kind (a permission in a "
                                   f"category only {who} may do is written as an action)")
    qa.add_argument("--kind", dest="add_kind", choices=["action", "permission"], default="action")
    qa.add_argument("--title", help="short header (100 characters at most; required without --guard)")
    qa.add_argument("--what", help=f"what {who} does or grants: the exact command when there is one (required "
                                   "without --guard)")
    qa.add_argument("--guard", help="a refusal of the owner, power or third-party guard (guard-...): its title, "
                                    "exact command (the question; and --command when Apply runs it) and reason come from the "
                                    "guards ledger, as an action")
    qa.add_argument("--context", help="two lines of context")
    qa.add_argument("--blocks", help="what waits on it")
    qa.add_argument("--item", action="append", help="WorkItem or Milestone it unblocks (repeatable)")
    qa.add_argument("--spec", action="append", help="spec node (repeatable)")
    qa.add_argument("--blocking", action="store_true")
    qa.add_argument("--due", help="YYYY-MM-DD: a stated deadline (it weighs above the count of what it unblocks)")
    qa.add_argument("--minutes", type=int, help=f"{who}'s effort in minutes (default 5 for an action, 1 for a "
                                                "permission)")
    qa.add_argument("--slug", help="id slug (default: from the title)")
    qa.add_argument("--session", help="the asking session's id")
    qa.add_argument("--command", help=f"an action's exact command, brain ... or install.ps1 ...: what {who}'s Apply "
                                      "shows and runs (brain queue apply ID, the cockpit's A)")
    qa.add_argument("--cwd", help="the folder --command runs in (default: the project's root)")
    qa.add_argument("--at", help="time asked (default: now)")
    qa.add_argument("--dry-run", action="store_true")
    qp = qs.add_parser("apply", help=f"{who}'s Apply: an action's exact command (its --command, else the one its text "
                                     f"names) shown, an install.ps1 -Apply's plan run first, then run once {who} "
                                     "answers y, logged as their action, then the action marked done; never from a "
                                     "Claude Code session's shell")
    qp.add_argument("id", help="a pending action DDR's id (or a part only it has)")
    qo = qs.add_parser("order", help=f"{who}'s own order: the entry first in its band, at position N (and --band to "
                                     "move it); it wins over the score; --clear gives it back to the score")
    qo.add_argument("id", help="an entry's id, as brain queue shows it")
    qo.add_argument("position", nargs="?", type=int, help="1 first")
    qo.add_argument("--band", choices=list(queue.BANDS))
    qo.add_argument("--clear", action="store_true")
    qo.add_argument("--by", default=by_)
    qo.add_argument("--at")
    qd = qs.add_parser("done", help=f"{who} did the action or granted the permission: a DDR is answered (the model "
                                    "then checks and acks it), a denial stamped in the ledger until denied again")
    qd.add_argument("id", help="a DDR id (or a part only one has), a denial's perm-... id or a guard refusal's "
                               "guard-... id")
    qd.add_argument("--note", help="what was done: granted by an allow rule, done once, ...")
    qd.add_argument("--by", default=by_)
    qd.add_argument("--at")

    sy = sub.add_parser("sync", help="research_graph sync --write, records graph, queue view, the features' "
                                     "statuses from merged PRs and FEATURES.md, kanban --write")
    sy.add_argument("--offline", action="store_true", help="no gh call (the features' statuses are not read)")
    sy.add_argument("--all", action="store_true", help="every project of the registry (a main checkout on main or "
                                                       "master is not written)")
    sy.add_argument("--force", action="store_true", help="write even when the running engine is not config.json "
                                                         "engine.pin (brain check says how they differ)")
    ck = sub.add_parser("check", help="records check, no conflict marker in the store, journals, decision logs and "
                                      "records, then research_graph check (--all: every project's, then the "
                                      "registry and the ids across every store)")
    ck.add_argument("--all", action="store_true", help="every project of the registry, then the registry's keys, "
                                                       "repos, stacks and code_index, and the ids across every store")
    ck.add_argument("--public", action="store_true", help="before a push to a public repo: no private term, secret, "
                                                          "personal data, data file or domain pattern (brain.public)")
    ck.add_argument("--repo", help="--public: the checkout to check (default: --root, else the current folder)")
    ck.add_argument("--remote", help="--public: the remote the push goes to (default: the one of public.repos, "
                                     "else origin)")
    ck.add_argument("--history", action="store_true", help="--public: the commits not on the remote yet too; a "
                                                           "green check stamps HEAD for the public guard")
    ck.add_argument("--engine", action="store_true", help="--public: the engine side of this checkout "
                                                          "(boundary.yaml), the extraction's dry run")
    ck.add_argument("--json", action="store_true", help="--public: stable keys")
    stt = sub.add_parser("status", help="each project's indicators at zero token: items, frontier, decisions, "
                                        "milestones, audit, stacks, code index, journals, records, ledgers")
    stt.add_argument("--all", action="store_true", help="every registered project, the totals and the ids shared "
                                                        "across stores")
    stt.add_argument("--quick", action="store_true", help="the files only: no audit, stack or code index probe")
    stt.add_argument("--json", action="store_true", help="stable keys, no timestamp")
    tu = sub.add_parser("tui", help=f"the cockpit: sessions and their steps, {who}'s queue, alerts, milestones, "
                                    "frontier, audit, stacks and index, digest; read-only, zero token")
    tu.add_argument("--all", action="store_true", help="every registered project, and every session")
    tu.add_argument("--refresh", type=_duration, default=cockpit.REFRESH_S, metavar="DURATION",
                    help="how often the panels' files are checked, re-read when changed: 500ms, 1s, 2s, 5s... "
                         "(default 2s)")
    tu.add_argument("--probe", type=_duration, default=cockpit.PROBE_S, metavar="DURATION",
                    help="how often alerts, audit, stacks and index, digest and the denied calls are read again "
                         "(default 5m; the r key: now)")
    tu.add_argument("--hours", type=float, default=cockpit.HOURS,
                    help=f"the sessions whose transcript was written in the last N hours (default {cockpit.HOURS:g})")
    tu.add_argument("--plain", action="store_true", help="the text view redrawn in place, even with the tui extra")
    tu.add_argument("--sort", action="append", default=[], metavar="PANEL:KEY",
                    help="a panel's sort, -KEY reversed: sessions:state|age|project|context|cost, "
                         "queue:unblocks|age|kind|project, frontier:priority|unblocks|milestone|age|project "
                         "(repeatable)")
    tu.add_argument("--filter", action="append", default=[], metavar="PANEL:FIELD=VALUE",
                    help="a panel's filter: sessions:state=open|all|asking|running|stale|idle|ended, "
                         "queue:kind=all|decision|action|permission, frontier:priority=all|P0-P1|P0-P2|none, "
                         "frontier:milestone=all|none|<id> (repeatable)")
    tu.add_argument("--search", default="", metavar="TEXT",
                    help="the rows holding every word of TEXT (ids, titles, projects; case ignored)")
    tu.add_argument("--tz", choices=cockpit.TZS,
                    help="the times shown: this machine's timezone (local, the interactive default) or UTC; --once "
                         "and --json keep the recorded UTC times unless it is given")
    tu.add_argument("--reset", action="store_true",
                    help="start from the defaults: forget the scope and views remembered in <BRAIN_HOME>/tui.json")
    tu.add_argument("--detail", metavar="ID",
                    help="print a row's detail and exit, as Enter shows it: a DDR (its options, its answer), an item "
                         "(props, spec sections, ADRs, PR, code), a milestone, a session (its plan; the start of its "
                         "id), an alert's key; its links and its actions with their exact commands (--json: the data)")
    tu.add_argument("--once", action="store_true", help="print the text view once and exit")
    tu.add_argument("--quick", action="store_true", help="with --once or --json: the files only, no probe")
    tu.add_argument("--json", action="store_true", help="the panels' data, once")
    up = sub.add_parser("update", help=f"a newer engine: the latest tag of config.json engine.repo, its CHANGELOG and "
                                       f"the plan (install it into the brain's venv, swap the launcher, the pin to "
                                       f"move by PR); installed on {who}'s yes only (y, or --yes), never from a "
                                       "Claude Code session")
    up.add_argument("--check", action="store_true", help="print the plan and exit: install nothing")
    up.add_argument("--yes", action="store_true", help="install without asking (the owner's own terminal)")
    up.add_argument("--json", action="store_true", help="the plan's data (stable keys)")
    us = sub.add_parser("usage", help="the token ledger: what the sessions cost, by project, item, class, phase, "
                                      "tool, command, day...; distributions and script candidates; quota: the plan's "
                                      "quota readings and forecast (zero token)")
    us.add_argument("what", nargs="?", choices=("quota", "guard", "allow"),
                    help="quota: note a get_usage reading (--observe) and forecast the plan's quota window; guard: what "
                         "the usage governor would decide now; allow: the owner's override of it (their own terminal)")
    us.add_argument("--observe", type=float, metavar="PCT",
                    help="quota: the percent used get_usage reads for --window, noted with its time")
    us.add_argument("--window", choices=tuple(quota.WINDOWS), default="week", help="quota: the window (default week)")
    us.add_argument("--resets", metavar="TIME", help="quota: when the window resets (get_usage's resetsAt, ISO; "
                                                     "default the last reading's, moved by whole weeks)")
    us.add_argument("--at", metavar="TIME", help="quota: when the reading was taken (ISO; default now)")
    us.add_argument("--hours", type=float, help="allow: how long the override holds (default 2; 0 ends it)")
    us.add_argument("--reason", help="allow: why, kept with the override")
    us.add_argument("--all", action="store_true", help="every session on this machine, whatever its project")
    us.add_argument("--since", help="Nd, Nw, today, yesterday, last-week, last-month or YYYY-MM-DD (default 7d)")
    us.add_argument("--until", help="the same, excluded (default: now)")
    us.add_argument("--by", choices=cost.DIMS, default="summary",
                    help="one breakdown (default: a summary of project, item, class, phase, tool, command and the "
                         "script candidates)")
    us.add_argument("--report", choices=("daily", "weekly"), help="the same as --by day or --by week")
    us.add_argument("--top", type=_whole, default=cost.TOP, help=f"rows per table (default {cost.TOP}; 0: all)")
    us.add_argument("--no-scan", action="store_true", help="read the ledger as it is, without scanning the "
                                                          "transcripts that changed")
    us.add_argument("--rescan", action="store_true", help="scan every transcript again (after a scanner change)")
    us.add_argument("--json", action="store_true")
    co = sub.add_parser("cost", help="estimate an item from the finished ones, review actual against estimate and "
                                     "budget, audit the estimates (zero token)").add_subparsers(dest="cost_cmd",
                                                                                                required=True)
    ce = co.add_parser("estimate", help="an item (id) or a brief (text, @FILE or -): cost, output, context peak, "
                                        "active time and sessions, median and p25-p75, from the most alike items")
    ce.add_argument("target", help="an item id, or a brief's text (@FILE: the file, -: stdin)")
    ce.add_argument("--class", dest="task_class", choices=cost.CLASSES, help="the task class (default: the item's "
                                                                              "or the brief's, else standard)")
    ce.add_argument("--record", action="store_true", help="write it on the item (props.cost_estimate)")
    ce.add_argument("--json", action="store_true")
    cr = co.add_parser("review", help="finished items' actual against their estimate and brief budget, and why")
    cr.add_argument("item", nargs="?", help="one item (default: the items finished in the window)")
    cr.add_argument("--since", default="last-week", help="the window's start (default last-week)")
    cr.add_argument("--until", help="the window's end, excluded (default: now)")
    cr.add_argument("--record", action="store_true", help="write each review on its item (props.cost_review)")
    cr.add_argument("--json", action="store_true")
    ca = co.add_parser("audit", help="the window's estimates off by more than x1.5 and why, the calibration per "
                                     "class, the costliest sessions, the script candidates")
    ca.add_argument("--since", default="last-week", help="the window's start (default last-week)")
    ca.add_argument("--until", help="the window's end, excluded (default: now)")
    ca.add_argument("--top", type=_whole, default=cost.TOP, help=f"rows per table (default {cost.TOP}; 0: all)")
    ca.add_argument("--write", action="store_true", help="keep it in <BRAIN_HOME>/usage/<project>/audit-*.md, and the "
                                                         "week's forecast snapshot in <BRAIN_HOME>/forecast/<project>")
    ca.add_argument("--json", action="store_true")
    fo = sub.add_parser("forecast", help="when each milestone and the whole backlog will be done: p10-p90 from a Monte "
                                         "Carlo of futures, under the honesty bar (zero token)")
    fo.add_argument("--all", action="store_true", help="every registered project, each alone")
    fo.add_argument("--runs", type=_whole, default=forecast.RUNS, help=f"futures (default {forecast.RUNS})")
    fo.add_argument("--seed", type=int, default=forecast.SEED, help=f"the draws' seed (default {forecast.SEED}): the "
                                                                    "same inputs and seed give the same numbers")
    fo.add_argument("--items", action="store_true", help="each item's p10 . p50 . p80 . p90, and why the others are "
                                                         "not dated")
    fo.add_argument("--no-scan", action="store_true", help="read the token ledger as it is, without scanning the "
                                                          "transcripts that changed")
    fo.add_argument("--json", action="store_true", help="the result with its seed, input digests and code version")
    pj = sub.add_parser("projects", help="the project registry resolved (every project, or --project's)")
    pj.add_argument("--keys", action="store_true", help="every key a project's entry may hold, and what it holds")
    pj.add_argument("--json", action="store_true", help="stable keys")
    ini = sub.add_parser("init", help="a new personal brain from the templates: config.json, projects.yaml, the graph "
                                      "store, journal, ADR log, starter rules (a plan; --apply writes it)")
    ini.add_argument("dir", nargs="?", help="the folder that becomes the brain's private repo (default: here)")
    ini.add_argument("--owner", help="the person or team who decides for it (config.json identity.owner; default: "
                                     "the owner of DIR's config.json, when it has one)")
    ini.add_argument("--template", default=init.DEFAULT_TEMPLATE,
                     help="the engine's template by name (default generic) or a folder holding a template.yaml")
    ini.add_argument("--kind", choices=init.KINDS, default="person", help="a person (default) or a team")
    ini.add_argument("--tenant", help="the tenant id, for a brain hosted for a team")
    ini.add_argument("--tier", choices=init.TIERS, default="lite",
                     help="the profile its machines start from (config.json tier.base; default lite)")
    ini.add_argument("--name", default="brain", help="its name in projects.yaml (default brain)")
    ini.add_argument("--apply", action="store_true", help="write it (default: the plan)")
    cf = sub.add_parser("config", help="the personal brain's config.json resolved: owner, registry, rules, memory, "
                                       "records, engine pin, public repos, denied terms, secrets by name")
    cf.add_argument("--keys", action="store_true", help="every key config.json may hold, and what it holds")
    cf.add_argument("--check", action="store_true", help="exit 1 when config.json breaks the contract")
    cf.add_argument("--json", action="store_true", help="stable keys")
    bd = sub.add_parser("boundary", help="every tracked file's side by boundary.yaml (engine, personal, claude, "
                                         "generated) and the readiness of the engine side")
    bd.add_argument("--check", action="store_true", help="exit 1 on a file no rule classifies, an engine rule "
                                                         "without a target or two files with one target")
    bd.add_argument("--side", choices=boundary.SIDES, help="list that side's files (engine: with their target)")
    bd.add_argument("--readiness", action="store_true", help="the denied terms found per engine file")
    bd.add_argument("--json", action="store_true", help="stable keys")
    rd = sub.add_parser("render", help="the neutral source (source/) written as an agent's own files: claude (the "
                                       "marketplace, byte for byte), agents (AGENTS.md, .agents/skills), cursor, "
                                       "gemini, antigravity, grok, hermes (brain.render)")
    rd.add_argument("--target", choices=render.TARGETS, default="claude", help="the agent (default claude)")
    rd.add_argument("--project", default=argparse.SUPPRESS, help="the project to render for (same as brain --project; "
                                                                 "default: the one here)")
    rd.add_argument("--repo", help="the project's checkout to write into, a worktree of it (default: its root)")
    rd.add_argument("--out", help="render into this folder instead: a dry run to look at")
    rdm = rd.add_mutually_exclusive_group()
    rdm.add_argument("--write", action="store_true", help="write what is not current, remove stray files")
    rdm.add_argument("--check", action="store_true", help="exit 1 when an output is not current")
    rd.add_argument("--force", action="store_true", help="with --write: replace a file brain render did not write, "
                                                         "and write even when the running engine is not config.json "
                                                         "engine.pin")
    rd.add_argument("--json", action="store_true", help="stable keys")
    cl = sub.add_parser("classes", help="every store's data class (config.json classes.stores) and where it may go "
                                        "(brain.classes)")
    cl.add_argument("paths", nargs="*", metavar="PATH", help="the store and class of each path (a repo path, "
                    "$BRAIN_HOME/... or ~/...)")
    cl.add_argument("--check", action="store_true", help="exit 1 on a store without a class or a destination its "
                                                         "class forbids")
    cl.add_argument("--json", action="store_true", help="stable keys")
    cl.add_argument("--suggest", action="store_true", help="a starting classes block for config.json, to edit")
    cl.add_argument("--matrix", action="store_true", help="how each class may take each exit")
    va = sub.add_parser("vault", help="seal stores to public recipients; the device key, the canaries, the drill "
                                      "(brain.vault)").add_subparsers(dest="vault_cmd", required=True)
    vs = va.add_parser("status", help="adapters, keystore, device key, recipients, last canaries and seals, the "
                                      "steps left to the owner")
    vs.add_argument("--json", action="store_true", help="stable keys")
    vl = va.add_parser("seal", help="seal a store to its recipients (public keys only, unattended)")
    vl.add_argument("store", help="a store of config.json classes.stores")
    vl.add_argument("paths", nargs="*", metavar="PATH", help="what to seal instead of the store's declared content")
    vl.add_argument("--out", help="the sealed file (default $BRAIN_HOME/vault/sealed/<store>/)")
    vl.add_argument("--adapter", choices=vault.ADAPTERS, help="age or gpg (default: config's, else age, else gpg)")
    va.add_parser("canary", help="the daily proof: a nonce sealed to each recipient alone, opened by this machine's "
                                 "device key")
    vr = va.add_parser("recipient", help="declare a public recipient").add_subparsers(dest="recipient_cmd",
                                                                                       required=True)
    vra = vr.add_parser("add", help="a plan, or --write into config.json; refuses a private key")
    vra.add_argument("name", help="kebab-case: the machine for a device key, recovery for the recovery key")
    vra.add_argument("--kind", required=True, choices=vault.KINDS)
    key = vra.add_mutually_exclusive_group(required=True)
    key.add_argument("--age", help="an age1... recipient or an ssh-ed25519 public key")
    key.add_argument("--gpg", help="an armored gpg public key file (copied into vault/keys/)")
    vra.add_argument("--host", help="the machine a device key belongs to")
    vra.add_argument("--write", action="store_true", help="write config.json")
    vd = va.add_parser("device", help="this machine's device key").add_subparsers(dest="device_cmd", required=True)
    vdi = vd.add_parser("init", help="create it straight into the OS keystore, print its public half (the "
                                     "owner's terminal only)")
    vdi.add_argument("--name", help="kebab-case (default: this machine's name)")
    vdi.add_argument("--adapter", choices=vault.ADAPTERS, help="age or gpg (default: age when found)")
    vo = va.add_parser("open", help="open a sealed file (the owner's terminal only)")
    vo.add_argument("file")
    vo.add_argument("--out", help="the folder to open into (default: <name>.opened beside the file)")
    vo.add_argument("--identity", help="a key file, or - to type or paste it, hidden (default: the device key)")
    vi = va.add_parser("drill", help="open a recipient's canary with its key and record the proof (the owner's "
                                     "terminal only)")
    vi.add_argument("recipient")
    vi.add_argument("--identity", help="a key file, or - to type or paste it, hidden (default -)")
    pe = sub.add_parser("permissions", help="the permission hierarchy: a project's effective allow / ask / deny list on "
                                            "this machine and where each rule comes from (brain.permissions)")
    pe.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    pe.add_argument("--all", action="store_true", help="every registered project")
    pe.add_argument("--machine", help="another machine's host name (default: this one)")
    pe.add_argument("--session", help="a declared session or sub-session: its rules too")
    pe.add_argument("--explain", metavar="RULE", help="a rule, a call (Bash: cmd) or a permission task (perm-...): "
                                                      "where it is declared, what it falls in, what the call gets")
    pe.add_argument("--days", type=int, default=30, help="how far back a perm-... id is looked for (default 30)")
    pe.add_argument("--json", action="store_true", help="the data: rules, sources, files, guards, never")
    pe.add_argument("--requests", action="store_true", help="the permission requests: brain queue's permission "
                    "entries and the rules granted for them, with scope, reason, items, milestones, what each "
                    "unblocks, sessions, evidence, duration and status")
    pe.add_argument("--status", choices=["pending", "granted", "expired"], help="--requests: one status")
    pe.add_argument("--scope", help="--requests: a scope's start (global, project, project quant, machine...)")
    pe.add_argument("--item", help="--requests: those that unblock this item or milestone")
    pe.add_argument("--search", help="--requests: a text in the id, reason or evidence")
    pe.add_argument("--sort", choices=list(permissions.REQUEST_SORTS), default="unblocks", help="--requests' order")
    ps = pe.add_subparsers(dest="permissions_cmd")
    ps.add_parser("check", help="permissions.yaml and allow-rules.txt checked: levels, rules, never-grantable and "
                                "broad allow rules; exit 1 on an error")
    pr = ps.add_parser("render", help="an adapter's settings files: the plan, or --write the missing rules (never "
                                      "removes one)")
    pr.add_argument("--target", default="claude", help="the agent's adapter (built: claude)")
    pr.add_argument("--level", choices=["user", "project", "local", "session"], default="project",
                    help="user: ~/.claude/settings.json (install.ps1 -Apply writes it); project: each repo's "
                         ".claude/settings.json; local: .claude/settings.local.json; session: a --settings file")
    pr.add_argument("--machine", default=argparse.SUPPRESS, help="another machine's host name")
    pr.add_argument("--session", default=argparse.SUPPRESS, help="the session level's name")
    pr.add_argument("--repo", help="the folder to render the project or local level into (a worktree of a "
                                   "production repo, for a PR there)")
    pr.add_argument("--write", action="store_true", help="add the missing rules (not the user file, not a "
                                                         "production checkout)")
    pr.add_argument("--out", help="session level: write the file for claude --settings there")
    pr.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                    help="the plans; with --level user, the user scope's rules by verdict (install.ps1 reads it)")
    pg = ps.add_parser("grant", help="a permission task becomes a rule appended to permissions.yaml in this branch "
                                     "(reviewed by PR); without --rule, the narrow rules proposed for the call")
    pg.add_argument("perm", nargs="?", help="a permission task of brain queue (perm-...)")
    pg.add_argument("--call", help="the call when it has no perm-... id: 'Bash: cmd'")
    pg.add_argument("--rule", help="the rule, Claude Code's syntax or Shell(...) for Bash and PowerShell")
    pg.add_argument("--verdict", choices=["allow", "ask", "deny"], default="allow")
    pg.add_argument("--why", help=f"the reason ({permissions.WHY_MIN} characters at least)")
    pg.add_argument("--by", help=f"who decided it: '{who}, 2026-11-02'")
    pg.add_argument("--global", dest="global_", action="store_true", help="the global level")
    pg.add_argument("--machine", default=argparse.SUPPRESS, help="the machine level (with --project: local)")
    pg.add_argument("--profile", help="the profile level")
    pg.add_argument("--tenant", help="the tenant level")
    pg.add_argument("--session", default=argparse.SUPPRESS, help="the session level")
    pg.add_argument("--days", type=int, default=argparse.SUPPRESS, help="how far back the perm-... id is looked for")
    du = pg.add_mutually_exclusive_group()
    du.add_argument("--until", help="the rule's last day, YYYY-MM-DD (default: indefinite)")
    du.add_argument("--for-days", dest="for_days", type=int, help="the rule holds N days from today")
    du.add_argument("--while", dest="while_", help="the rule holds while this item is open")
    pg.add_argument("--dry-run", action="store_true", help="print the line, write nothing")
    pf = sub.add_parser("profile", aliases=["doctor"],
                        help="this machine's facts, its profile (Lite, Défaut, Recommandé, Personnalisable), each "
                             "capability's and stack's state, and the Recommended profile, at zero token")
    pf.add_argument("--json", action="store_true", help="the report as JSON: the machines brick's inventory fields, "
                                                        "then a brain block")
    pf.add_argument("--quick", action="store_true", help=f"no probe that starts a program ({', '.join(probe.SLOW)})")
    pfs = pf.add_subparsers(dest="profile_cmd")
    pfl = pfs.add_parser("list", help="each profile's entries, Recommandé computed for this machine")
    pfw = pfs.add_parser("show", help="one profile's entries: class, requirements, cost, fallback and state")
    pfw.add_argument("name", choices=tiers.PROFILES)
    for sp in (pfl, pfw):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    for name, text in (("set", "the plan of this machine's profile; --apply writes $BRAIN_HOME/profile.json"),
                       ("render", "what install.ps1 reads, as JSON: the pip extras and the stacks on and off")):
        sp = pfs.add_parser(name, help=text)
        sp.add_argument("base", nargs="?", choices=tiers.BASES,
                        help="the base (recommended: the set this machine allows, frozen into the overrides); none: "
                             "the current one")
        sp.add_argument("--with", dest="with_", action="append", metavar="ID",
                        help="turn a capability or stack on (repeatable; all: every built entry)")
        sp.add_argument("--without", action="append", metavar="ID", help="turn a capability or stack off (repeatable)")
        if name == "set":
            sp.add_argument("--apply", action="store_true", help="write the choice (a second apply changes nothing)")
    rf = sub.add_parser("refresh", help="sync then check for the project's stores, or every registered project's")
    rf.add_argument("--offline", action="store_true", help="no gh call (the features' statuses are not read)")
    rf.add_argument("--all", action="store_true", help="every project of the registry")
    rf.add_argument("--force", action="store_true", help="write even when the running engine is not config.json "
                                                         "engine.pin")
    rf.add_argument("--on-main", action="store_true",
                    help="also write in a main checkout on main or master (by default it is only checked)")
    td = sub.add_parser("tidy", help="the project's stale worktrees and merged branches (and origin's with --remote), "
                                     "listed, then removed with --apply; never an unmerged branch or a dirty worktree")
    td.add_argument("--all", action="store_true", help="every project of the registry")
    td.add_argument("--remote", action="store_true", help="also origin's branches merged into the default branch "
                                                          f"(git ls-remote; deleting them is {who}'s)")
    td.add_argument("--apply", action="store_true", help="remove them: git worktree remove, git branch -d; with "
                                                         "--remote, git push origin --delete outside a Claude Code "
                                                         f"session only (in one: the brain queue add for {who})")
    td.add_argument("--json", action="store_true", help="the plan as JSON (no --apply)")
    rs = sub.add_parser("resume", help="the resume pack: the project's present state, stable to volatile, at zero "
                                       "token (on demand; the SessionStart hook says how old the written one is)")
    rs.add_argument("--all", action="store_true", help="every project of the registry, one pack each")
    rs.add_argument("--budget", type=int, default=resume.BUDGET,
                    help=f"tokens (~{resume.CHARS_PER_TOKEN} characters each), cut from the volatile end; 0: no limit "
                         f"(default {resume.BUDGET})")
    rs.add_argument("--write", action="store_true", help="also keep it in <BRAIN_HOME>/resume/<project>.md")
    rs.add_argument("--offline", action="store_true", help="do not ask gh for the open PRs")
    rs.add_argument("--health", action="store_true", help="check the project's stacks (~1 s each at most)")
    rs.add_argument("--notes", action="append", help="a folder of hand-over notes to read first (repeatable; "
                                                     "defaults: $BRAIN_NOTES, else <BRAIN_HOME>/handover and the "
                                                     "desktop app's session-group notes folders)")
    rs.add_argument("--hook", action="store_true", help="SessionStart hook: hook JSON on stdin, one line saying "
                                                        "whether the pack is written and how old it is")
    dg = sub.add_parser("digest", help="the digest: what happened in a window (milestones, closed items, ADRs, DDRs, "
                                       "merged PRs, session records, journal), newest first, at zero token")
    dg.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    dg.add_argument("--all", action="store_true", help="every project of the registry, one digest each")
    dg.add_argument("--since", default="last-week", help=f"first day included: {digest.WHEN} (the day it was "
                                                         "reached); default last-week, seven days before today")
    dg.add_argument("--until", default="today", help="last day included, same forms (default today)")
    dg.add_argument("--budget", type=int, default=digest.BUDGET,
                    help=f"tokens (~{resume.CHARS_PER_TOKEN} characters each): sections lowered from full text to "
                         f"one line each to counts, the journal first, then lines cut from the end; 0: no limit "
                         f"(default {digest.BUDGET})")
    dg.add_argument("--write", action="store_true", help="also keep it in <BRAIN_HOME>/digest/<project>/"
                                                         "<since>_<until>.md (the resume pack names the latest)")
    dg.add_argument("--offline", action="store_true", help="do not ask gh for the merged PRs")
    dg.add_argument("--json", action="store_true", help="print the records gathered (before any condensing) as JSON")
    for name, text in (("up", "start stacks and their dependencies, in dependency order; a healthy one is untouched, "
                              "except a Compose stack (docker compose up -d applies a changed compose file)"),
                       ("down", "stop stacks (every one with a stop command when none is named), reverse order"),
                       ("health", "check the named stacks, else the watched ones (--all: every one); starts nothing; "
                                  "STALE: a Compose stack's containers differ from its compose file; code-index (or "
                                  "--all): STALE when a repo's branch moved past its indexed commit")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("stacks", nargs="*", metavar="STACK")
        if name == "up":
            sp.add_argument("--force", action="store_true", help="run the named stacks' start command even when "
                            "healthy, to apply a changed configuration (docker compose up -d recreates what changed)")
        if name == "health":
            sp.add_argument("--all", action="store_true", help="every declared stack, then the code index")
            sp.add_argument("--hook", action="store_true", help="SessionStart hook: hook JSON on stdin, the watched "
                            "stacks that are down as context, silent when all is well")
    bu = sub.add_parser("bundle", help="the Compose bundles the engine ships (sovereign: OpenTelemetry collector, "
                                       "Prometheus, Loki, Grafana, Qdrant): the plan, then the apply (brain.bundles)"
                        ).add_subparsers(dest="bundle_cmd", required=True)
    for name, text in (("plan", "checks (ports on 127.0.0.1, images pinned, docker compose config), the files, "
                                "folders and images, and what the apply would do with each component; writes and "
                                "starts nothing"),
                       ("apply", "render into <BRAIN_HOME>/stacks/<bundle>, pull the missing images, start the "
                                 "components (brain up); a second apply changes nothing")):
        sp = bu.add_parser(name, help=text)
        sp.add_argument("bundles", nargs="*", metavar="BUNDLE", help="default: every bundle the engine ships")
        if name == "plan":
            sp.add_argument("--json", action="store_true", help="the plan as JSON")
        else:
            sp.add_argument("--no-start", dest="start", action="store_false",
                            help="write the files and folders only; brain up <bundle> starts it later")
    au = sub.add_parser("audit", help="what misses the standard per repo and module, at zero token (brain.audit); "
                                      "--diff: the scout on a change (brain.scout)")
    au.add_argument("--all", action="store_true", help="every registered project, then the milestone line")
    au.add_argument("--repo", action="append", help="only this repo of the project (repeatable)")
    au.add_argument("-v", "--verbose", action="store_true", help="every finding, info included")
    au.add_argument("--json", action="store_true", help="stable keys, no timestamp")
    au.add_argument("--trend", nargs="?", type=int, const=5, default=0, metavar="N",
                    help="also re-measure the last N completed ISO weeks at their end commit (default 5)")
    au.add_argument("--fail-on", choices=list(audit.SEVERITIES), help="exit 1 on a finding at this severity or above")
    au.add_argument("--write", action="store_true", help=f"write {audit.VIEW} (one project, from a worktree)")
    au.add_argument("--items", action="store_true", help="one debt item per repo with debt, priority proposed "
                                                         "(one project, from a worktree)")
    au.add_argument("--diff", nargs="?", const="", default=None, metavar="BASE|A..B",
                    help="the scout: from merge-base(HEAD, the default branch, or BASE) to the working tree, or the "
                         "commits A..B")
    au.add_argument("--repo-dir", metavar="D", help="--diff: the repo changed (default: the current folder)")
    au.add_argument("--store", dest="audit_store", metavar="DIR",
                    help="--diff: a code store in a worktree (a cross-repo change)")
    au.add_argument("--limit", type=_whole, metavar="N",
                    help="--diff: LEFT units to fix in this PR (default: scout_limit, 3)")
    au.add_argument("--pr-body", metavar="FILE", help="--diff: the PR body ('-' for stdin), where the structure "
                                                      "signals read Root cause: and Justified: lines (the range's "
                                                      "commit messages are read too)")
    ix = sub.add_parser("index", help="have GitNexus (re)index the repos declared under code_index: (no name and no "
                                      "flag: each repo's state)")
    ix.add_argument("repos", nargs="*", metavar="REPO", help="a repo's folder name (GitNexus's name for it)")
    ix.add_argument("--all", action="store_true", help="every declared repo, even one indexed at its branch head")
    ix.add_argument("--stale", action="store_true", help="only the repos not indexed at their branch head (of the "
                                                         "named ones, else of every one)")
    li = sub.add_parser("lint", help=f"lint {who}'s rules at zero token").add_subparsers(dest="lint_cmd",
                                                                                         required=True)
    lr = li.add_parser("rules", help="tokens injected per session, duplicates, script and guard candidates, hard "
                                     "rules (enforced_by); exit 1 when the injected rules pass the hook cap")
    lr.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    lr.add_argument("--all", action="store_true", help="every project of the registry, compared with each other")
    lr.add_argument("--json", action="store_true")
    lr.add_argument("--propose", action="store_true", help="file the next batch of candidates as DDRs in this repo's "
                                                           "decision queue, the most useful first")
    lr.add_argument("--max", type=int, default=lint.MAX_PENDING,
                    help=f"rules-lint DDRs pending at once at most (default {lint.MAX_PENDING})")
    lr.add_argument("--dry-run", action="store_true", help="with --propose: say what would be filed")
    lr.add_argument("--session", help="the asking session's id")
    lr.add_argument("--at", help="time asked (default: now)")
    me = sub.add_parser("memory", help="memory shared across machines by a reviewed PR: status, sync").add_subparsers(
        dest="memory_cmd", required=True)
    ms = me.add_parser("status", help="what a sync would do, note by note; writes nothing")
    ms.add_argument("--offline", action="store_true", help="against main as last fetched (no network)")
    my = me.add_parser("sync", help="sync now in the foreground: import, secret scan, export to the machine's branch "
                                    "of the day and its PR")
    my.add_argument("--export-only", action="store_true", help="import nothing (main's newer notes stay listed)")
    tm = sub.add_parser("timed", help="run a command and append its execution-time event to the ledger")
    tm.add_argument("--task", help="the step's name (default: the command line)")
    tm.add_argument("--project", default=argparse.SUPPRESS, help="default: $BRAIN_PROJECT, else the registered project "
                                                                 "of the current folder, else the repo's name")
    tm.add_argument("--version", dest="code_version", help="what runs (default: $BRAIN_VERSION, else the short SHA of "
                                                           "HEAD of the current folder's repo)")
    tm.add_argument("--shell", action="store_true", help="run the command line through the system shell")
    tm.add_argument("--quiet", action="store_true", help="no line on stderr")
    tm.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command and its arguments")
    pf = sub.add_parser("perf", help="the slowest steps, trends, regressions and time lost per week, from the ledger")
    pf.add_argument("--project", default=argparse.SUPPRESS, help="only this project (default: every one)")
    pf.add_argument("--since", help=f"Nd, Nw, YYYY-MM-DD or an ISO time (default: {perf.SINCE_DAYS}d)")
    pf.add_argument("--task", help="only the tasks that contain this text (any case)")
    pf.add_argument("--top", type=int, default=perf.TOP, help=f"rows of the slowest steps and trends (default "
                                                              f"{perf.TOP}; 0: all)")
    pf.add_argument("--from", dest="sources", action="append", metavar="PATH",
                    help="a JSONL file or a folder of them to read instead of the ledger (repeatable)")
    pf.add_argument("--engine", action="store_true", help="the engine's own runs instead (every brain command and "
                                                          "hook, brain.selftime): its slow steps, regressions, hook time "
                                                          "per week and the errors it caught")
    pf.add_argument("--json", action="store_true")
    al = sub.add_parser("alerts", help="each project's open alerts (scheduler, ledger, stacks, code index, audit, its "
                                       "events and files); --notify sends the changes through brain notify")
    al.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    al.add_argument("--all", action="store_true", help="every project of the registry")
    al.add_argument("--quick", action="store_true", help="the files and events only: no scheduler, stack, code index "
                                                         "or audit probe")
    al.add_argument("--json", action="store_true", help="stable keys, no timestamp of its own")
    al.add_argument("--fail-on", choices=list(alerts.LEVELS), help="exit 1 when an alert at this level or above is "
                                                                    "open")
    al.add_argument("--notify", action="store_true", help="send the new, risen and failed alerts through brain notify "
                                                          "(resolved ones at info) and record the pass")
    al.add_argument("--dry-run", action="store_true", help="with --notify: what would be sent; nothing sent or recorded")
    als = al.add_subparsers(dest="alerts_cmd")
    for name, text in (("raise", "open an alert (or update it: a new level or message)"),
                       ("resolve", "resolve an alert")):
        a = als.add_parser(name, help=f"{text}: an alert event in $BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl")
        a.add_argument("key", help="the alert's stable id within the project (freshness:returns_matic)")
        a.add_argument("message", nargs="?", default="", help="one line ('-': stdin, @FILE: the file)")
        a.add_argument("--level", choices=list(alerts.LEVELS),
                       help="its level, the notify level it is sent at (default: warn; resolve: info)")
        a.add_argument("--task", help="what it is about (default: the key)")
        a.add_argument("--source", help="who raises it: a monitor, a CLI, a watchdog")
        a.add_argument("--code", help="a catalogued code (an exit code, a scheduler result, a name)")
        a.add_argument("--link", help="a URL or a path to look at")
    no = sub.add_parser("notify", help="the notification channels: ntfy, Telegram, e-mail, per project and level "
                                       "(projects.yaml notify:)").add_subparsers(dest="notify_cmd", required=True)
    ns = no.add_parser("send", help="send through the project's route for the level; exit 1 when nothing delivered")
    ns.add_argument("message", nargs="?", default="", help="the text ('-': stdin, @FILE: the file)")
    ns.add_argument("--level", required=True, choices=list(notify.LEVELS))
    ns.add_argument("--title", help="a short title (default: the message's first line)")
    ns.add_argument("--source", help="who sends: watchdog, decision, a task's name...")
    ns.add_argument("--key", help="an alert's stable id: not sent again at this level within the throttle")
    ns.add_argument("--link", help="a URL the notification opens")
    ns.add_argument("--channel", action="append", help="these declared channels only, every one of them (a test)")
    ns.add_argument("--force", action="store_true", help="send even within the throttle")
    ns.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing")
    ns.add_argument("--json", action="store_true")
    nt = no.add_parser("status", help="channels, their environment variables (set or missing, never their values), "
                                      "the project's routes, the last sends")
    nu = no.add_parser("setup", help="a channel's setup steps (the TUI wizard's): ntfy, telegram, email or a name")
    nu.add_argument("target", metavar="CHANNEL")
    nu.add_argument("--find-chat", action="store_true", help="telegram: the chats that wrote to the bot (getUpdates; "
                                                             "sends nothing)")
    for sp in (ns, nt, nu):
        sp.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    nt.add_argument("--all", action="store_true", help="every project of the registry")
    # --- the wave's cost (wi-brain-generated-merge, wi-brain-collisions, wi-brain-brief-generate) ---
    mg = sub.add_parser("merge-driver", help="the git merge driver of the generated views, the logs and the graph's "
                                             "YAML: git runs it, install defines it in a repo's git config").\
        add_subparsers(dest="merge_cmd", required=True)
    mgr = mg.add_parser("run", help="git's entry: merge.brain.driver = brain merge-driver run %%O %%A %%B %%P %%L")
    for name in ("base", "ours", "theirs", "path"):
        mgr.add_argument(name)
    mgr.add_argument("size", nargs="?", default="7", help="the conflict marker size (%%L)")
    mgi = mg.add_parser("install", help="define the driver in the repo's git config (its worktrees share it): the "
                                        "plan, or --apply; checks .gitattributes names it")
    mgi.add_argument("--repo", help="the repo (default: the one here)")
    mgi.add_argument("--launcher", help="the brain command git runs (default: brain on PATH, else this Python)")
    mgi.add_argument("--apply", action="store_true", help="write the git config (idempotent)")
    mgi.add_argument("--json", action="store_true")
    mgs = mg.add_parser("status", help="the views the driver kept from one side here, waiting for brain refresh")
    mgs.add_argument("--repo", help="the worktree (default: the one here)")
    mgs.add_argument("--json", action="store_true")
    mgp = mg.add_parser("replay", help="past merges merged again by git merge-tree, as text then with the driver "
                                       "(nothing checked out): the conflicted files before and after")
    mgp.add_argument("merges", nargs="*", metavar="MERGE", help="a merge commit, or OURS..THEIRS (two heads); none: "
                                                                "every merge reachable from HEAD (--since)")
    mgp.add_argument("--since", default="", help="the merges since this date (git log --since)")
    mgp.add_argument("--repo", help="the repo (default: the one here)")
    mgp.add_argument("--json", action="store_true")
    co_ = sub.add_parser("collisions", help="the files each open branch and worktree touches, crossed with the "
                                            "startable items' predicted surface: who can start now, who waits on whom")
    co_.add_argument("--all", action="store_true", help="every project of the registry")
    co_.add_argument("--frontier", action="store_true", help="every startable item, not only the P0/P1 ones")
    co_.add_argument("--json", action="store_true")
    br = sub.add_parser("brief", help="a sub-session's brief written from the graph (the coordinator edits only "
                                      "what needs judgement)")
    br.add_argument("item")
    br.add_argument("--class", dest="task_class", default="standard", help="trivial, standard (default) or strategic: "
                                                                            "the model and effort (brief.classes)")
    br.add_argument("--budget", default="", help="the context budget (400k, 600k, 800k, 1M; default: the class's)")
    br.add_argument("--coordinator", default="", help="the coordinator's app session id (default: "
                                                      "$CLAUDE_CODE_HOST_SESSION_ID)")
    br.add_argument("--notes", default="", help="the shared notes folder (default: the desktop app's for the "
                                                "coordinator, when it exists)")
    br.add_argument("--write", default="", help="also write the brief to this file")
    br.add_argument("--json", action="store_true")
    # --- coverage (wi-brain-test-coverage) ---
    cv = sub.add_parser("coverage", help="a repo's line coverage under its tests, with test contexts: printed, kept "
                                         "in the store with --write (the tested_by links, test.coverage)")
    cv.add_argument("--repo", default="", help="a repo of the project (default: the one that holds the store)")
    cv.add_argument("--run", action="store_true", help="run the repo's pytest suites under pytest-cov")
    cv.add_argument("-n", dest="workers", default="", help="pytest-xdist workers for --run (auto, 8...)")
    cv.add_argument("--python", default="", help="the Python that runs the tests (default: this one)")
    cv.add_argument("--from", dest="from_data", default="", help="a coverage data file (.coverage, run with "
                                                                  "--cov-context=test) instead of a run")
    cv.add_argument("--cwd", default="", help="with --from: the folder pytest ran in (default: the repo's root)")
    cv.add_argument("--write", action="store_true", help="keep the summary in the store: coverage/<repo>.json")
    cv.add_argument("--json", action="store_true")
    ses = sub.add_parser("sessions", help="the session tree: both ids, role, parent, children, state, context and "
                                          "each child's report (zero token)")
    ses_sub = ses.add_subparsers(dest="sessions_cmd")
    for name, help_ in (("tree", "the families with a live member, or ID's family, with the children's reports"),
                        ("show", "one session by either id or its short name: what a message would meet")):
        sp_ = ses_sub.add_parser(name, help=help_)
        sp_.add_argument("ref", nargs="?" if name == "tree" else None, default="",
                         help="an app id (local_..., a prefix of 8 or more), a transcript id or a short name")
        if name == "show":
            sp_.add_argument("--report", action="store_true", help="its last final message in full, from its "
                                                                   "transcript (never stored)")
    for sp_ in (ses, *ses_sub.choices.values()):
        sp_.add_argument("--hours", type=float, default=24.0, help="active in the last H hours (default 24)")
        sp_.add_argument("--all", action="store_true", help="every session, archived ones included")
        sp_.add_argument("--no-briefs", action="store_true", help="skip the token ledger's brief hash")
        sp_.add_argument("--json", action="store_true")
    cap = sub.add_parser("capture", help="hook entry: the hook JSON on stdin (prints nothing)")
    cap.add_argument("event", choices=["session-start", "post-tool-use", "stop", "session-end"])
    cap.add_argument("family", nargs="?", default="", choices=["", "git", "gh"])
    _project_after(p)
    return p


NO_PROJECT = {"capture", "announce", "memory", "sessions"}  # the hooks', memory and sessions (machine-wide)


def _project_after(parser: argparse.ArgumentParser) -> None:
    """--project after the subcommand too (brain status --project quant), on every leaf subcommand but NO_PROJECT."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sp in action.choices.items():
                if name in NO_PROJECT:
                    continue
                if any(isinstance(a, argparse._SubParsersAction) for a in sp._actions):
                    _project_after(sp)
                elif "--project" not in sp._option_string_actions:
                    sp.add_argument("--project", default=argparse.SUPPRESS,
                                    help="a registered project (same as brain --project)")


def _whole(text: str) -> int:
    """argparse type: a whole number (0 or more)."""
    try:
        n = int(text)
    except ValueError:
        n = -1
    if n < 0:
        raise argparse.ArgumentTypeError(f"a whole number, 0 or more ({text!r})")
    return n


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # records and logs are UTF-8; a pipe on Windows defaults to cp1252
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    with selftime.run(selftime.command_task(args)):  # the engine's exec event, and an error event if it raises
        return _dispatch(args)


def _dispatch(args) -> int:
    if args.cmd == "capture":
        return capture.main([args.event] + ([args.family] if args.family else []))
    if args.cmd == "decision" and args.decision_cmd == "announce":  # a hook: standard library only, never fails
        return decisions.hook_main([args.event])
    if args.cmd == "health" and args.hook:  # a hook: never fails, silent when all is well
        return stacks.hook_main(["SessionStart"])
    if args.cmd == "resume" and args.hook:  # a hook: never fails, one line
        return resume.hook_main(["SessionStart"])
    if args.cmd == "memory":  # machine-wide: every project's memory folder, no repo root
        return memory.main_cli(args.memory_cmd, getattr(args, "offline", False), getattr(args, "export_only", False))
    if args.cmd == "timed":  # machine-wide ledger: a project name is a label, the registry is not needed
        return timing.run(args.command, task=args.task, project=args.project, version=args.code_version,
                          shell=args.shell, quiet=args.quiet)
    if args.cmd == "perf":
        return perf.main(project=args.project, since=args.since, task=args.task, top=args.top, sources=args.sources,
                         as_json=args.json, engine=args.engine)
    if args.cmd == "init":  # a new brain has no graph store yet
        return init.main(args)
    if args.cmd == "merge-driver":  # git's entry and a repo's git config: no graph store
        return cmd_merge_driver(args)
    if args.cmd == "sessions":  # the machine's sessions: no graph store
        return cmd_sessions(args)
    root = Path(args.root).resolve() if args.root else None
    if args.cmd == "update":  # the engine of this machine: a brain without a graph store updates too
        return cmd_update(args, root)
    if args.cmd == "audit":  # its repos may have no graph store: before find_root
        return audit.main(args, root)
    if args.cmd == "check" and args.public:  # a public repo has no graph store: before find_root
        return public.main(Path(args.repo).resolve() if args.repo else root or Path.cwd(), history=args.history,
                           remote=args.remote or "", engine=args.engine, as_json=args.json)
    if args.cmd in ("index", "up", "down", "health"):  # stack and repo names are global: any project's registry
        if args.project:
            projects.get(args.project, root)  # an unknown project stops here
        if args.cmd == "index":
            return codeindex.main(args.repos, args.all, args.stale, root, project=args.project)
        if args.cmd == "health":
            return cmd_health(args, root, args.project)
        return stacks.main(args.cmd, args.stacks, False, root, getattr(args, "force", False), project=args.project)
    if args.cmd == "bundle":  # bundles and stack names are global, like brain up
        return bundles.main(args.bundle_cmd, args.bundles, root, start=getattr(args, "start", True),
                            as_json=getattr(args, "json", False))
    if args.cmd == "doctor":
        args.cmd = "profile"
    if args.project:
        args.project_obj = projects.get(args.project, root)
        root = args.project_obj.root
    root = root or paths.find_root()
    if args.cmd == "record":
        return {"sr": cmd_record_sr, "ar": cmd_record_ar, "ddr": cmd_record_ddr, "backfill": cmd_record_backfill,
                "check": cmd_record_check, "sync": cmd_record_sync}[args.record_kind](args, root)
    return {"item": cmd_item, "features": cmd_features, "milestone": cmd_milestone, "spec": cmd_spec,
            "journal": cmd_journal, "adr": cmd_adr,
            "decision": cmd_decision, "queue": cmd_queue, "sync": cmd_sync, "check": cmd_check,
            "refresh": cmd_refresh, "tidy": cmd_tidy, "resume": cmd_resume, "digest": cmd_digest, "lint": cmd_lint,
            "notify": cmd_notify, "alerts": cmd_alerts, "status": cmd_status, "projects": cmd_projects,
            "config": cmd_config, "boundary": cmd_boundary, "render": cmd_render, "classes": cmd_classes,
            "vault": cmd_vault, "permissions": cmd_permissions,
            "profile": cmd_profile,
            "tui": cmd_tui, "usage": cmd_usage, "cost": cmd_cost, "forecast": cmd_forecast,
            "collisions": cmd_collisions, "brief": cmd_brief, "coverage": cmd_coverage}[args.cmd](args, root)


if __name__ == "__main__":
    sys.exit(main())
