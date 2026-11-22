# Releasing

A tag `vX.Y.Z` is both `research-graph` and `brain` at X.Y.Z. A release has four moves, in this order: the version PR,
the tag, the pin, the machines. The maintainer prepares the PRs; the owner of the repo pushes and tags. Nothing here
runs by itself: the jobs below refuse what they can check, and the rest is this list.

`vX.Y.Z` is the new tag, and `vP` the last one, below.

## The version policy

Which number moves is decided by what an owner has to do, not by how much changed. Before 1.0:

| The release holds | The number | Example |
|---|---|---|
| a change an owner must act on: a numbered step of `### Upgrade` beyond the standard steps below, anything that newly refuses what passed, a config or a git setting to rewrite | the middle one, `0.Y.0` | 0.2.6, a patch before this policy, would be 0.Y.0 under it (guards fail closed, `brain update` twice) |
| a format that moves: a registered schema changed since `vP` (`SCHEMAS` in `packages/brain/installer/release_check.py`), what `brain init` wrote once; config.json's schema grown by optional keys only, and a whole new format, do not move (below) | the middle one, `0.Y.0` | 0.2.5, a patch before this policy, would be 0.Y.0 under it (the Lesson type, the `merge=brain` line) |
| only what needs nothing: fixes and additions an owner gets by the standard steps alone | the last one, `0.Y.Z` | a fix of a crash |

**An optional key of config.json is a patch's** (wi-brain-release-schema-additive): when `config.schema.json` only gains
optional properties (none of them `required`) or changes its prose (`description`, `title`, `$comment`, `examples`),
every config.json the old schema accepted is still valid and an owner has nothing to do; `release-check` reports it as
grown, not moved. The same holds for `permissions.schema.json`, for `docgraph.schema.json` (docgraph/v1 is read
tolerantly: an optional key added within v1 is a patch's, the owner's answer of 2026-11-12; removing or narrowing one
stays a minor) and for `catalogue.schema.json`, read by the same rule. Any other change of it moves the format: a key
removed, a keyword added, removed or changed (a type, an enum, a bound, a pattern, `additionalProperties`, `required`),
even a list reordered; the comparison errs towards a minor version. **A whole new format is a patch's too**: a format
the last tag did not register (its own `SCHEMAS`) and none of whose files exists there (`release_check.new_formats`) is
held by no brain yet and never read by an older engine; a file new to a format that exists still moves it, and so does a
format whose files are renamed. A record schema (ar, ddr, sr, event) moves even by an optional key, since older engines
on other machines read the records this one writes. A new refusal of what passed stays a minor version: ship it off by
default, behind a key the owner turns on, to keep a patch.

From 1.0 on, the first number takes the middle one's place for a change that breaks a brain; that is decided at 1.0.

- **Each release has a theme and says so**: the wave it was planned for, in the heading of its section of
  `packages/brain/CHANGELOG.md`, `## X.Y.Z — YYYY-MM-DD — theme`, and in its tag message. Work outside the theme
  waits for the next release, unless it is a fix that cannot wait.
- **A fix that cannot wait** (a brain that no longer starts, a guard that refuses every commit, data lost) is a patch
  cut from the last tag, not a release of whatever main holds: its PR merges on main first, then a branch `release/X.Y`
  from `vX.Y.Z` (made once per minor) takes it by cherry-pick with its fragment, and the version PR of
  `X.Y.Z+1` targets that branch. The tag is cut there (« 3. The tag », from `release/X.Y` instead of main), then
  `release/X.Y` merges back into main by a PR, so that the tag is in main's history and the next `compat-prev`
  upgrades from it; that PR deletes the fix's fragment from main (its `changes/` file), since `## X.Y.Z+1` now holds
  it, and the CHANGELOGs' `merge=brain` (`.gitattributes`) unions the released section into main's. It
  holds the fix and nothing else, so it needs nothing beyond the standard steps.
- **The cadence**: a release a week, the wave planned for it with its theme; a week with nothing merged has none. The
  review fixes of a wave's PRs are released on the cadence, in the next wave, never as a patch of their own unless
  they are a fix that cannot wait.
- **`release-check` refuses** a patch (X.Y the last tag's, Z after it) when a registered schema moved since `vP`, or
  when its `### Upgrade` numbers a step whose bold title is not a standard step's; and any version whose `### Upgrade`
  does not number each standard step under its title, whose brain section heading names no theme after its date
  (punctuation alone is none), or whose section in either CHANGELOG repeats an
  entry an earlier section released (a fix that cannot wait, left in `## Unreleased` by the merge back; compared by
  text, a « No change » line and the `### Upgrade` steps aside). It reads files and titles, not meanings: a step written
  as prose, a change that newly refuses with no step for it, or a repeated entry reworded on the way, is the version
  PR's author to catch, with « Read what changed » below.

Every release up to 0.2.7 predates this policy, and every one after 0.2.0 was cut as a patch, the ones that would now
be minor versions included (0.2.5 and 0.2.6 above). 0.2.7 is the last release before this policy: its `### Upgrade`
had a step beyond the standard ones (step 4, a script that runs `brain --project P` from a worktree), and it stayed a
patch (the maintainer's decision, 2026-11-09). The check would refuse its steps 2 and 3 as well: they are standard
steps under their older titles, **Restart Claude Code's sessions** and **In each public repo's checkout**. The check
runs against the tag before a version, so it never judges 0.2.7.

### The standard steps

What every release asks of an owner, whatever it changed. A patch's `### Upgrade` numbers these and nothing else, each
opening with its title in bold as here (a title is compared without its case or a closing `.` or `:`); a minor one
numbers them too, in their place among its own steps. `release-check` refuses a version that leaves one out. With
nothing else to do, the section says « Nothing to run for the rest » after them.

```markdown
1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then `brain release apply` instead (from the release
   that adds it; before it, the installer's `-Apply`).
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: a stamp is valid only under the engine that made it, so the push guard refuses the
   old one. From 0.4.0 on, `brain update` and the installer's `-Apply` refresh them (`brain check --public --refresh`:
   each local checkout of `public.repos` in the registry); by hand, `brain check --public --history` in a checkout
   they skipped (uncommitted work, named in their output) or outside the registry, before its next push.
```

### The release preview

So that a PR that would make the next release a minor one is seen when it is opened, not at the version PR
(wi-brain-release-preview; the owner's decision of 2026-11-10), CI's `release-preview` job runs on every pull request
`python packages/brain/installer/release_check.py --preview --base origin/<the PR's target>`: the version policy above,
applied now as if the next release were a patch of `vP`, to

- the registered schemas that moved since `vP` (the same comparison as `release-check`: an optional config key and a
  whole new format are reported as compatible with a patch);
- the steps of the pending Upgrade fragments (`packages/brain/changes/`) beyond the standard ones: a fragment's
  numbered lines, or its first line when it opens with a bold title (the step the version PR will number); a closing
  paragraph such as « Nothing to run for the rest » is no step.

It says « a patch », or « a minor » and whether this PR carries the reasons (« because of this PR », « already before
this PR », or how many of them), naming each with « (this PR) », in the job's summary. It is advisory: it exits 0
whatever it says (2 when it cannot tell: no tag), and a minor version stays the owner's decision at the version PR.
Run it from a branch before pushing, committed or not. Making it a required check is a branch-protection setting.

`--ref REF` previews a commit instead of the working tree (read with git, the checkout left as it is), and `--json`
prints the preview as data: the release it would be (`kind`, `release`, `patch`, `minor`), each reason with the first
commit since the tag that brought it, and `tipped_by`, the first of them (with the merged PR's number when its subject
names one). The brain reads it (wi-brain-wave-version-forecast): `brain next` under the current wave's head and
`brain wave check X.Y.Z` after the closure rule say whether the wave named for the next patch ships as that patch or
as a minor, the PR that first tipped it and why, so that the version and the wave's name are decided before the
version PR. They run the preview of the engine checkout's remote default branch as git last fetched it
(`origin/HEAD`, else `origin/main`), with that commit's own two scripts (read with `git show` into a temporary
folder), bounded to a minute; a project with no engine checkout gets no forecast, and one that cannot be read is said
in one line. Advisory: neither command's exit changes.

`release-check` itself refuses, on every PR, a standard step that the pending Upgrade fragments ask twice: one fragment
holds the standard steps for the whole release, and a PR's fragment adds only its own step, never a copy of them
(les-brain-upgrade-fragment-copies-standard).

## 1. Before the version PR

- The items named for this release are merged, each reviewed, CI green on Windows (the `brain` job) included.
- **The merged PRs close their items first**: `brain wave close-merged X.Y.Z` reads, in each repo of the project,
  the PRs merged since the last release tag (git alone: GitHub's merge or squash commits on the default branch),
  maps each to its items by the changelog fragment it added (`changes/<item>.md`, or a slug that starts with the
  item's id) or an item id in its title, and plans each open item's close (`--pr "<repo> #N"`, the PR's title as
  the outcome, dated by its merge; a revert takes its PR out); `--write` closes them, refused while a repo could not
  be read. It lists the items already closed, the PRs and fragments that name no item and the wave's open items no
  merged PR names: those are carried or dropped next. Fetch first: the default branch is read as last fetched.
- **The version PR closes its wave** (the closure rule). Where a store plans the releases as waves (a Milestone of
  kind wave whose release is a label, `packages/brain/docs/formats.md`, « Milestone kinds »), the wave of this
  version (its label, or the current wave when the release jumped to the next minor or major: the release forecast
  of `brain next` says it from the first PR that tips it) may hold no open item that is neither carried by name to a later wave nor dropped: in the brain that holds
  that store, `brain wave close X.Y.Z --carry-to X.Y.Z+1 [--drop ID]... --write` writes each open item's
  `props.carried_to` (or drops it), reaches the wave with what it did and `props.shipped_as` X.Y.Z (the later
  waves' releases are computed from it), then `brain sync` (a PR there, like any
  backlog change). `--carry-to` names a pending wave, created beside the closed one when its release has none yet: a
  reached or dropped one is refused, since no live wave would show the item; `--carry-to` is read as the plan stands
  once the wave is closed (after a jump to X.Y.0, `--carry-to X.Y.1` is the wave that follows). `release_check.py
  --store <that store>` refuses the version PR until then (an open item left, the wave not reached yet, or another
  pending wave left below the version), naming the items, and `brain wave check X.Y.Z` says the same from the brain;
  its line names the engine that read the store. CI holds no owner's store and does not run it, so the maintainer
  runs it by hand before opening the version PR. A version that names two waves (a later wave pinned to the current
  wave's jump) is refused as ambiguous. A store with no wave of this version passes when no pending wave is below
  it. A wave reached without `props.shipped_as` (by hand, or by an engine up to 0.5.0, which wrote none) is read
  through the last tag, which `release_check.py` knows (`brain wave check X.Y.Z --tag vP` from the brain): the wave
  labelled the tag's release shipped as itself, and the one reached after it ships as this version, so it is that
  wave the rule checks. When the tag does not tell and that wave, the one before the version's (none) or before the
  current wave it would jump, could have shipped as this version (the next minor or major after what it counts
  from), the version PR is refused instead of reading the wrong wave or none (wave 0.3.3 closed by hand and shipped
  as 0.4.0: 0.4.0 named no wave, or jumped onto the next one); `brain item set <wave> props.shipped_as=X.Y.Z`
  records it. The line names the wave it checked, and how when it ships under another number (`wave-s3 (1.0.2,
  closed as 1.1.0, a jump)`, `its props.shipped_as`, `reached after the last tag vP`). `brain next` then shows the
  next wave, the carried items first.
- `compat-prev` is green on main's latest PR: the upgrade test goes from the last tag to HEAD and back
  ([`packages/brain/docs/formats.md`](../packages/brain/docs/formats.md), « The upgrade test »).
- **Read what changed**: `git log vP..origin/main` and `git diff --stat vP origin/main`. Look for what a brain that
  already exists does not get by itself:
  - a schema or a format (`packages/brain/src/brain/schemas/`, `tests/fixtures/formats/`);
  - what `brain init` wrote once and keeps afterwards (`templates/generic/`, the store's `schema.yaml`);
  - the hooks (`adapters/claude/hooks/`: `brain sync` and a restart of the sessions);
  - anything that newly refuses, or a stamp or cache that a new engine invalidates.
- **Choose the number** by « The version policy » above: any of these that asks an owner something beyond the
  standard steps makes it `0.Y.0`, and so does a format that moves, a registered schema changed since `vP` or what
  `brain init` wrote once, even with no step for it. Only what an owner gets by the standard steps alone is `0.Y.Z`.
  `release-check` refuses a patch that changes a file `SCHEMAS` registers (the formats, and part of what `brain init`
  writes once), save config.json's schema grown by optional keys and a whole new format (above); a file `brain init`
  writes that it does not register is yours to see.

## 2. The version PR

One branch, `chore/release-X.Y.Z`, one PR that moves the version and nothing else. Its mechanical part is one
command, run in that branch's checkout: `brain release prepare X.Y.Z --theme "..."` prints the plan (the version lines
of the table below, `freeze_store.py vP`, `changelog.py compile`, `FEATURES.md` and `docs/reference/` rendered from the
planning brain, `release_check.py --store` then `--preview`), and `--write` runs it in that order, stopping at the
first step that fails. What it leaves to you, it names: the `### Upgrade` steps and their prose, the pilot page's line
of what each release brought, and the review.

| File | What moves |
|---|---|
| `src/research_graph/__init__.py`, `packages/brain/src/brain/__init__.py` | `__version__` |
| `packages/brain/pyproject.toml` | the research-graph pin, to `vX.Y.Z` |
| `packages/brain/src/brain/adapters/claude/hooks/common.sh` | `brain_version` |
| `README.md`, `packages/brain/README.md`, `docs/install.md`, `docs/pilot.md` | the install lines and what the new tag brings |
| `packages/brain/installer/stranger_test.py` | the default `--ref`, and the usage line |
| `packages/brain/tests/fixtures/stores/vP/` | the brain `vP` wrote, frozen (« The fixture freeze » below) |
| `CHANGELOG.md`, `packages/brain/CHANGELOG.md` | the fragments compiled into `## X.Y.Z — YYYY-MM-DD`, and `## X.Y.Z — YYYY-MM-DD — theme` in the brain's (`python packages/brain/installer/changelog.py compile X.Y.Z --theme "..." --write`, which deletes them); a distribution with no fragment still gets its section, in one line opening « No change » |
| the `### Upgrade` section, `packages/brain/CHANGELOG.md` | see below |

**The wave's reference.** The release notes of a wave name its rendering as of that wave, which the maintainer
renders on a machine with the brain that plans it, after the wave is closed: `brain reference --asof wave-X.Y.Z`
(`<BRAIN_HOME>/views/reference/<project>/wave-X.Y.Z/`, never committed; packages/brain/docs/views.md, « The reference
as of a point »).

**The `### Upgrade` section** is the first thing in the brain's section, and `brain update` prints it. Numbered steps
for what an owner must do from `vP`, in the order that works, each opening with its title in bold and then its reason
and what fails until it is done, the standard steps under their own titles; then what needs nothing, said so.
Everything else is under `### Changes`. Check it against the `compat-prev` report of the PR: what the test had to run,
the section says. Every release numbers at least the standard steps (« The standard steps »), so none has nothing to
do: a release that asks nothing more says « Nothing to run for the rest » after them. Each PR on the way writes its
entry as a fragment, never in the CHANGELOG (`packages/brain/changes/<item>.md` for the brain, `changes/<item>.md` for
research-graph: a first line `section: Upgrade|Added|Fixes|Changes`, a blank line, the entry; the folders' READMEs),
so that parallel PRs never collide in one `## Unreleased`; `changelog.py compile` puts them in the section order
Upgrade, Added, Fixes, Changes, and the version PR then numbers the Upgrade steps. Within a section, a list fragment
after a list continues it, and anything else (a closing paragraph such as « Nothing to run for the rest ») gets a blank
line before it, so it never reads as the last step's continuation.

**The fixture freeze.** `packages/brain/tests/fixtures/formats/<format>/v<N>/` holds what the readers are tested on, and
it only grows: an `older` file is what a released engine wrote, and is never edited. By hand:

- a format whose `v` moved adds its folder `v<N>` with `older` and `newer` files, and a migration (`formats.md`);
- a new format adds its folder and its entry in `SCHEMAS` (`packages/brain/installer/release_check.py`), and the upgrade
  test places it, or fails;
- an additive change under the same `v` extends the `newer` file only.

And by a script, **the old store** (wi-brain-old-store-fixture): the brain `vP`'s engine writes through its own
commands, frozen under `packages/brain/tests/fixtures/stores/vP/`, on which the tests run every store-reading command
of this checkout (`packages/brain/docs/formats.md`, « The old stores »). The version PR adds it; `release-check`
refuses a version PR without it:

```bash
python packages/brain/installer/freeze_store.py vP      # installs vP in a fresh venv, writes the brain, freezes it
pytest packages/brain/tests/test_old_stores.py packages/brain/tests/test_formats_frozen.py
```

The same run freezes each format's file as `vP` wrote it, `tests/fixtures/formats/<format>/v<N>/vP.<ext>`
(`packages/brain/docs/formats.md`, « Fixtures »).

A test that fails there is a change that breaks a brain `vP` made: fix it, or it is a format that moves (a minor
version, with its `### Upgrade` step).

**The jobs on this PR.** All of them run on every pull request; two matter here (`release-preview`, « The release
preview », only says what `release-check` will judge):

- **`release-check`** (`packages/brain/installer/release_check.py`) sees that this is a version PR because `__version__`
  is not the last tag's. It fails when a registered schema changed since the last tag and this version's section has no
  `### Upgrade` with something in it, when the two `__version__`, the pin, `brain_version` and the two dated sections
  do not agree, when the brain's section names no theme, when its `### Upgrade` leaves out a standard step, when a
  patch breaks the version policy (a schema change, a step beyond the standard ones), when a section of either
  CHANGELOG repeats an entry an earlier one released, or when no store of `vP` is frozen (« The fixture freeze »). Run it before pushing:
  `python packages/brain/installer/release_check.py`, with `--store <the store that plans the releases>` where
  one does (section 1, the closure rule: CI runs it without, as it holds no owner's store; a `--store` it cannot
  read is exit 2).
  It reads files, not meanings: a section can be there and wrong (`permissions.yaml`'s keys are constants of
  `brain.permissions`, described by `permissions.schema.json`, which a test keeps in step). What a schema change narrows (a property removed, a field
  newly required...) is `brain schema diff`'s, on every PR (CI's advisory `schema-diff` job;
  `packages/brain/docs/formats.md`, « The schema diff »): a narrowing that reaches the version PR unresolved by a
  `Compat:` line is a format that moves. This list still applies.
- **`compat-prev`** installs `vP`, writes every registered format, installs this checkout over it, runs the store plan,
  `brain sync`, `brain check` and the Lite scenario, rolls back to `vP` and comes back. The pin of a tag not cut yet does
  no harm: it installs from the checkout.

Before merging, from the branch: `pytest packages/brain -p no:randomly -n auto -m "not docker"` and
`brain check --public --history`. Then merge the PR by its normal review. **Nothing else merges until the tag**: the
jobs read the PR, and a schema merged after it would reach the tag with no job having seen it.

## 3. The tag: the owner

From an up-to-date main, at the version PR's merge commit. The tag message names the release's theme, the one its
section heading names (« The version policy »). **The tag is signed** (STD-3, from v0.3.2 on): `git tag -s` with the
owner's SSH release key, so that `brain update` and the installer can tell it from a tag pushed by someone else
(wi-brain-release-signing; the key, the `releaser` role and `allowed_signers`:
[`packages/brain/docs/identity.md`](../packages/brain/docs/identity.md), « Signed releases »):

One command does it, in the owner's own terminal (wi-brain-release-tag-command), from the engine checkout:

```bash
brain release tag vX.Y.Z                              # its plan, one y, then your key's passphrase
```

It prints its plan, asks one y (`--yes` in a script of yours; `--json` prints the plan and runs nothing), then runs the
lines below in order and stops at the first that fails, saying which: the switch (refused while a tracked file has
changes: nothing is switched, stashed or reset), the pull, the tag not on the remote yet, HEAD the version PR's merge
(its message names `release-X.Y.Z`, both `__version__` are the version and its first parent's another, so a PR merged
after it is refused; the brain's CHANGELOG holds `## X.Y.Z — date — theme`, whose theme makes the tag message), the two public checks, `git tag -s` (git asks your key's
passphrase; the engine never reads a key), the verification against the planning brain's allowed signers (`--planning`,
else `--root`, else the personal brain: members.yaml's `releaser` keys, else its `allowed_signers`), the push of
the tag object verified. A rerun
resumes: a local tag already at HEAD (a push that failed) is verified and pushed; one elsewhere is said, never moved.
It is an owner gesture (`brain.gestures`): refused in an agent's session after its plan, and the owner guard refuses
it to a session's tool call (`packages/brain/docs/guards.md`). The command exists from the release that adds it: the
tag of that release itself is cut with the lines below (the engine installed is still the previous one), or with
the checkout's own engine (`python -m brain release tag vX.Y.Z` from a venv where this checkout is installed). `--branch release/X.Y` tags a fix that cannot wait
(below); `--repo` names the checkout, `--remote` the remote (default `origin`). By hand, the same lines:

```bash
git switch main
git pull --ff-only
git log -1 --oneline                                  # the merge of chore/release-X.Y.Z
brain check --public --history                        # the stamp the push guard reads
brain check --public --private-text                   # no sentence of your rules or notes in the engine
git tag -s vX.Y.Z -m "brain X.Y.Z and research-graph X.Y.Z — theme: what it brings"   # your key's passphrase
git -c gpg.ssh.allowedSignersFile=<your brain>/allowed_signers verify-tag vX.Y.Z      # Good "git" signature for <you>
git push origin vX.Y.Z
```

Signing needs, once: the key made in the owner's own terminal, its public half and the `releaser` role in the
personal brain's `members.yaml`, `brain identity allowed-signers --write` committed there, and git's
`gpg.format ssh` and `user.signingkey` set (identity.md gives the lines). A tag made with `-a` by mistake is
unsigned: delete it before pushing it (`git tag -d vX.Y.Z`) and sign it again; once pushed, a tag is never moved.

**A fix that cannot wait** (« The version policy ») is tagged the same way from `release/X.Y`, at the merge of its
version PR, instead of main: `brain release tag vX.Y.Z --branch release/X.Y`, or by hand `git switch release/X.Y`,
then `git pull --ff-only` and the lines after it. Then
`release/X.Y` merges back into main by a PR, which deletes from main every fragment that `## X.Y.Z+1` now holds:
the next version PR's `release-check` refuses a section that repeats an entry already released, word for word; one
reworded during the cherry-pick is yours to see.

CI's `release-tag` job then checks that the tag, both `__version__` and the pin agree. It does not check the theme of
the tag message: `release-check` checked it in the section heading, and the owner copies it. It says whether the
tag carries an SSH signature (a notice, or a warning for an unsigned one) and never fails on it: the keys that
verify it are in the owner's `allowed_signers`, not in this repo, so the verification is `brain update`'s and the
installer's, before they install (refused only where `config.json` `engine.verify_tags` is on). Once it is green,
`brain update --check` on a machine at `vP` shows the new version and its `### Upgrade`. A tag is never moved: a
mistake is a new version, a patch when its fix needs nothing beyond the standard steps (« The version policy »).

## 4. The pin and the machines

A brain stays on its pin until it moves, so this is what releases the tag to a brain. Its `### Upgrade` section has the
steps for that version; in general:

- **A brain with an installer of its own** (`config.json` `engine.installer`): a PR in the brain that moves `engine.pin`
  to `vX.Y.Z`, with anything else its brain holds that names the version, and the rules that follow the engine's change
  (in the same PR, so that they never name a command the pin does not have). Run `brain sync` with the new engine (a venv at the tag: the machine's own is still the
  old one, and sync refuses another engine than the pin), so the hooks it renders go in too. After its merge, on each machine, in the owner's
  terminal, one command: `brain release apply` (wi-brain-release-apply; `--planning ROOT`, else `--root`, else the
  brain checkout holding the current folder, else the personal brain). It checks the checkout's pin against the default branch's
  (`git fetch` first, unless `--offline`; refused when they differ: the installer reads the main checkout), runs the
  installer without arguments and shows its plan, asks one y (`--yes` in a script of yours), then in order, stopping at the first step that fails and
  saying which: `<installer> -Apply` (its output and prompts in your terminal), `brain --version` of the engine now
  installed (`<BRAIN_HOME>/venv`'s, what the hooks run) against `engine.pin`, the engine clone fast-forwarded
  (`config.json` `engine.clone`, else the registry's checkout of `engine.repo`; only on its remote's default branch,
  clean and in no merge or rebase, never switched, reset or
  stashed: any other state is said and left, not a failure; `--offline` leaves it), `brain release verify` with the
  new engine (`--no-tests` passed on), and the open sessions of this machine named, to restart yourself (nothing is
  restarted or sent; an index that cannot be read is said). An owner gesture: refused in an agent's session after
  the installer's plan, and by the owner guard (category `release`, never queued: the installer needs your
  terminal). The release that adds it is installed with the installer's `-Apply` by hand. By hand, the same: `<installer> -Apply` (its plan first), then restart the
  sessions. The mechanical part is one command, run in a branch of that brain with the tag's engine:
  `brain release pin vX.Y.Z [--planning ROOT]` (default: the brain checkout holding the current folder) prints the
  plan (`--json` as data) and `--write` writes it, refused on the brain's default branch: `engine.pin` moved in `config.json` (its keys, order, indent, line endings and BOM kept),
  the engine stores its `classes:` block leaves at their default added there (`brain classes --suggest`'s lines, the
  running engine's), the adapter plugin's shim `PIN` line when the brain keeps one; it lists the tag's Upgrade steps
  since the pin that name `config.json` (read from the code host; the standard install step aside), to make by hand, and the brain's open PRs whose title
  or body names the version (the lot PRs that waited for the tag). `brain sync`, the ADR and the journal stay by hand.
- **Each install verifies the tag** first, against the brain's `allowed_signers`: `verify   vX.Y.Z: signed by <you>`
  in the plan of `brain update` and of the installer, else why not; with `engine.verify_tags` on, an unsigned tag is
  refused there, and so is a rollback to one (every tag up to v0.3.1): turn it off first to roll back. The check runs
  in the installer of the tag being installed: a brain's own installer that clones the engine at the pin and runs
  that clone verifies it only if it runs `git verify-tag` on the clone first (identity.md, « Signed releases »: the
  bootstrap's checks, offline), and the installer says whether it runs from the signed commit.
- **A brain from `brain init`** (no `engine.installer`): `brain update` in the owner's terminal, then `y`. It installs
  the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. Then restart the sessions. An engine older
  than 0.2.6 runs that update and only reminds of the pin: run `brain update` once more.
- **Each public repo's checkout**: a stamp is valid only under the engine that made it, so an upgrade makes the push
  guard refuse the old one. `brain update` and the installer's `-Apply` (from 0.4.0) run `brain check --public
  --refresh` with the new engine: each clean checkout of `public.repos` that the registry lists is checked with its
  history and stamped again; one with uncommitted work is skipped and named, and gets `brain check --public
  --history` by hand before its next push, as does a checkout outside the registry.

Tell anyone running a pilot of the tag, with the link to the section at that tag.

## Where a release stands

`brain release status [X.Y.Z]` reads where a release stands, at zero token, from the planning brain (`--planning`,
else `--root`, else the brain checkout holding the current folder, else the personal brain). The version is the one
given, else the lowest live wave's release above the pin, else the pin's own. Six steps, each `done`, `pending` or
`unknown`, then the first pending one as the next step, with whose it is:

| Step | Done when | Next move while pending, and its owner |
|---|---|---|
| wave | the wave of that release is `reached` (`brain wave close`) | the coordinator closes it |
| version | the version PR, whose title names « Release » and the version, is merged (or the tag is cut) | the coordinator: `brain release prepare`, then its PR's review and merge |
| tag | the tag is on the engine repo and signed by a releaser of `allowed_signers` (brain.tagsig, the tag fetched alone into a temporary folder) | the owner, named by their display name: « 3. The tag » |
| pin | `engine.pin` on the planning brain's default branch is at the tag (read from the local refs: as of the last fetch); while not, an open PR whose title names « pin » and the version | the coordinator: `brain release pin vX.Y.Z --write` in a pin branch, its PR, the merge |
| install | the engine running is at the version, on this machine | the owner: `brain release apply` (a brain with an installer of its own), else `brain update` |
| verified | this machine's last `brain release verify` passed at the version | the session: `brain release verify` |

Every read is bounded (60 s) and none writes. A read that fails (gh or git missing, the network down) leaves its step
`unknown` with why, never a « not started » it could not see (a tag whose signature could not be checked, a pin that could not be read); `--offline` reads no network (the version, tag and pin PR steps; the default branch from `origin/HEAD`, else `main`). `--json` prints the steps. The
install and the verify are this machine's: each machine runs `brain release verify` after its install.

`brain release verify` runs the after-install checks in one call, each with this interpreter (the engine installed),
in its own process and with its own timeout, its output in `$BRAIN_HOME/release/<check>.log` and one line on screen:

- **version**: `brain --version` against the planning brain's `engine.pin`;
- **probes**: `brain probes`, this machine's dependency probes;
- **classes**: `brain classes --check`, the store classes;
- **tests**: `python -m pytest tests -q` in the planning brain, when it has a `tests` folder and this interpreter has
  pytest (else said and skipped; `--no-tests` skips them), within an hour.

It writes `$BRAIN_HOME/release/verified.json` (`v` 1, derived: the next verify rebuilds it; the store `release` of
`packages/brain/docs/vault.md`), which `status` reads, and exits 0 when every check passed, 1 when one failed.
