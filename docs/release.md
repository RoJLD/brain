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

**An optional key of config.json is a patch's** (wi-brain-release-schema-additive): when `config.schema.json` only
gains optional properties (none of them `required`) or changes its prose (`description`, `title`, `$comment`,
`examples`), every config.json the old schema accepted is still valid and an owner has nothing to do; `release-check`
reports it as grown, not moved. Any other change of it moves the format: a key removed, a keyword added, removed
or changed (a type, an enum, a bound, a pattern, `additionalProperties`, `required`), even a list reordered; the
comparison errs towards a minor version. **A whole new format is a patch's too**: a format the last tag did not
register (its own `SCHEMAS`) and none of whose files exists there (`release_check.new_formats`) is held by no brain
yet and never read by an older engine; a file new to a format that exists still moves it, and so does a format
whose files are renamed. A record schema (ar, ddr, sr, event) moves even by an
optional key, since older engines on other machines read the records this one writes. A new refusal of what passed
stays a minor version: ship it off by default, behind a key the owner turns on, to keep a patch.

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
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.
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

`release-check` itself refuses, on every PR, a standard step that the pending Upgrade fragments ask twice: one fragment
holds the standard steps for the whole release, and a PR's fragment adds only its own step, never a copy of them
(les-brain-upgrade-fragment-copies-standard).

## 1. Before the version PR

- The items named for this release are merged, each reviewed, CI green on Windows (the `brain` job) included.
- **The version PR closes its wave** (the closure rule). Where a store plans the releases as waves (a Milestone of
  kind wave named by its release, `packages/brain/docs/formats.md`, « Milestone kinds »), the wave named by this
  version may hold no open item that is neither carried by name to a later wave nor dropped: in the brain that holds
  that store, `brain wave close X.Y.Z --carry-to X.Y.Z+1 [--drop ID]... --write` writes each open item's
  `props.carried_to` (or drops it), reaches the wave with what it did, then `brain sync` (a PR there, like any
  backlog change). `--carry-to` names a pending wave, created beside the closed one when its release has none yet: a
  reached or dropped one is refused, since no live wave would show the item. `release_check.py --store <that store>` refuses the version PR until then (an open item left, or
  the wave not reached yet), naming the items, and `brain wave check X.Y.Z` says the same from the brain; CI holds
  no owner's store and does not run it, so the maintainer runs it by hand before opening the version PR. A store
  with no wave of this version passes. `brain next` then shows the next wave, the carried items first.
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

One branch, `chore/release-X.Y.Z`, one PR that moves the version and nothing else:

| File | What moves |
|---|---|
| `src/research_graph/__init__.py`, `packages/brain/src/brain/__init__.py` | `__version__` |
| `packages/brain/pyproject.toml` | the research-graph pin, to `vX.Y.Z` |
| `packages/brain/src/brain/adapters/claude/hooks/common.sh` | `brain_version` |
| `README.md`, `packages/brain/README.md`, `docs/install.md`, `docs/pilot.md` | the install lines and what the new tag brings |
| `packages/brain/installer/stranger_test.py` | the default `--ref`, and the usage line |
| `CHANGELOG.md`, `packages/brain/CHANGELOG.md` | the fragments compiled into `## X.Y.Z — YYYY-MM-DD`, and `## X.Y.Z — YYYY-MM-DD — theme` in the brain's (`python packages/brain/installer/changelog.py compile X.Y.Z --theme "..." --write`, which deletes them); a distribution with no fragment still gets its section, in one line opening « No change » |
| the `### Upgrade` section, `packages/brain/CHANGELOG.md` | see below |

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
it only grows: an `older` file is what a released engine wrote, and is never edited. By hand for now (a `brain fixtures freeze` command is planned,
wi-brain-old-store-fixture):

- a format whose `v` moved adds its folder `v<N>` with `older` and `newer` files, and a migration (`formats.md`);
- a new format adds its folder and its entry in `SCHEMAS` (`packages/brain/installer/release_check.py`), and the upgrade
  test places it, or fails;
- an additive change under the same `v` extends the `newer` file only.

**The jobs on this PR.** All of them run on every pull request; two matter here (`release-preview`, « The release
preview », only says what `release-check` will judge):

- **`release-check`** (`packages/brain/installer/release_check.py`) sees that this is a version PR because `__version__`
  is not the last tag's. It fails when a registered schema changed since the last tag and this version's section has no
  `### Upgrade` with something in it, when the two `__version__`, the pin, `brain_version` and the two dated sections
  do not agree, when the brain's section names no theme, when its `### Upgrade` leaves out a standard step, when a
  patch breaks the version policy (a schema change, a step beyond the standard ones), or when a section of either
  CHANGELOG repeats an entry an earlier one released. Run it before pushing:
  `python packages/brain/installer/release_check.py`, with `--store <the store that plans the releases>` where
  one does (section 1, the closure rule: CI runs it without, as it holds no owner's store; a `--store` it cannot
  read is exit 2).
  It reads files, not meanings: a section can be there and wrong, and `permissions.yaml`, whose keys are constants in
  `brain.permissions`, has no file for it to compare (wi-brain-schema-diff compares keys). This list still applies.
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

```bash
git switch main
git pull --ff-only
git log -1 --oneline                                  # the merge of chore/release-X.Y.Z
brain check --public --history                        # the stamp the push guard reads
git tag -s vX.Y.Z -m "brain X.Y.Z and research-graph X.Y.Z — theme: what it brings"   # your key's passphrase
git -c gpg.ssh.allowedSignersFile=<your brain>/allowed_signers verify-tag vX.Y.Z      # Good "git" signature for <you>
git push origin vX.Y.Z
```

Signing needs, once: the key made in the owner's own terminal, its public half and the `releaser` role in the
personal brain's `members.yaml`, `brain identity allowed-signers --write` committed there, and git's
`gpg.format ssh` and `user.signingkey` set (identity.md gives the lines). A tag made with `-a` by mistake is
unsigned: delete it before pushing it (`git tag -d vX.Y.Z`) and sign it again; once pushed, a tag is never moved.

**A fix that cannot wait** (« The version policy ») is tagged the same way from `release/X.Y`, at the merge of its
version PR, instead of main: `git switch release/X.Y`, then `git pull --ff-only` and the lines after it. Then
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
  old one, and sync refuses another engine than the pin), so the hooks it renders go in too. After its merge, on each machine: `<installer> -Apply` (its plan first), then restart
  the sessions.
- **Each install verifies the tag** first, against the brain's `allowed_signers`: `verify   vX.Y.Z: signed by <you>`
  in the plan of `brain update` and of the installer, else why not; with `engine.verify_tags` on, an unsigned tag is
  refused there, and so is a rollback to one (every tag up to v0.3.1): turn it off first to roll back.
- **A brain from `brain init`** (no `engine.installer`): `brain update` in the owner's terminal, then `y`. It installs
  the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. Then restart the sessions. An engine older
  than 0.2.6 runs that update and only reminds of the pin: run `brain update` once more.
- **Each public repo's checkout**: `brain check --public --history` before its next push. A stamp is valid only under
  the engine that made it, so an upgrade makes the push guard refuse the old one.

Tell anyone running a pilot of the tag, with the link to the section at that tag.
