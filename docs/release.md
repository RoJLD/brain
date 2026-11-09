# Releasing

A tag `vX.Y.Z` is both `research-graph` and `brain` at X.Y.Z. A release has four moves, in this order: the version PR,
the tag, the pin, the machines. The maintainer prepares the PRs; the owner of the repo pushes and tags. Nothing here runs
by itself: the jobs below refuse what they can check, and the rest is this list.

`vX.Y.Z` is the new tag, and `vP` the last one, below.

## 1. Before the version PR

- The items named for this release are merged, each reviewed, CI green on Windows (the `brain` job) included.
- `compat-prev` is green on main's latest PR: the upgrade test goes from the last tag to HEAD and back
  ([`packages/brain/docs/formats.md`](../packages/brain/docs/formats.md), « The upgrade test »).
- **Read what changed**: `git log vP..origin/main` and `git diff --stat vP origin/main`. Look for what a brain that
  already exists does not get by itself:
  - a schema or a format (`packages/brain/src/brain/schemas/`, `tests/fixtures/formats/`);
  - what `brain init` wrote once and keeps afterwards (`templates/generic/`, the store's `schema.yaml`);
  - the hooks (`adapters/claude/hooks/`: `brain sync` and a restart of the sessions);
  - anything that newly refuses, or a stamp or cache that a new engine invalidates.

## 2. The version PR

One branch, `chore/release-X.Y.Z`, one PR that moves the version and nothing else:

| File | What moves |
|---|---|
| `src/research_graph/__init__.py`, `packages/brain/src/brain/__init__.py` | `__version__` |
| `packages/brain/pyproject.toml` | the research-graph pin, to `vX.Y.Z` |
| `packages/brain/src/brain/adapters/claude/hooks/common.sh` | `brain_version` |
| `README.md`, `packages/brain/README.md`, `docs/install.md`, `docs/pilot.md` | the install lines and what the new tag brings |
| `packages/brain/installer/stranger_test.py` | the default `--ref`, and the usage line |
| `CHANGELOG.md`, `packages/brain/CHANGELOG.md` | `## Unreleased` becomes `## X.Y.Z — YYYY-MM-DD`; a distribution with no change still gets its section, in one line |
| the `### Upgrade` section, `packages/brain/CHANGELOG.md` | see below |

**The `### Upgrade` section** is the first thing in the brain's section, and `brain update` prints it. Numbered steps
for what an owner must do from `vP`, in the order that works, each with its reason and what fails until it is done;
then what needs nothing, said so. Everything else is under `### Changes`. Check it against the `compat-prev` report of
the PR: what the test had to run, the section says. A release with nothing to do says « Nothing to run ».

**The fixture freeze.** `packages/brain/tests/fixtures/formats/<format>/v<N>/` holds what the readers are tested on, and
it only grows: a released fixture is never edited. By hand for now (a `brain fixtures freeze` command is planned,
wi-brain-old-store-fixture):

- a format whose `v` moved adds its folder `v<N>` with `older` and `newer` files, and a migration (`formats.md`);
- a new format adds its folder and its entry in `SCHEMAS` (`packages/brain/installer/release_check.py`), and the upgrade
  test places it, or fails;
- an additive change under the same `v` extends the `newer` file only.

**The jobs on this PR.** All of them run on every pull request; two matter here:

- **`release-check`** (`packages/brain/installer/release_check.py`) sees that this is a version PR because `__version__`
  is not the last tag's. It fails when a registered schema changed since the last tag and this version's section has no
  `### Upgrade` with something in it, or when the two `__version__`, the pin, `brain_version` and the two dated sections
  do not agree. Run it before pushing: `python packages/brain/installer/release_check.py`.
  It reads files, not meanings: a section can be there and wrong, and `permissions.yaml`, whose keys are constants in
  `brain.permissions`, has no file for it to compare (wi-brain-schema-diff compares keys). This list still applies.
- **`compat-prev`** installs `vP`, writes every registered format, installs this checkout over it, runs the store plan,
  `brain sync`, `brain check` and the Lite scenario, rolls back to `vP` and comes back. The pin of a tag not cut yet does
  no harm: it installs from the checkout.

Before merging, from the branch: `pytest packages/brain -p no:randomly -n auto -m "not docker"` and
`brain check --public --history`. Then merge the PR by its normal review.

## 3. The tag: the owner

From an up-to-date main, at the version PR's merge commit:

```bash
git switch main
git pull --ff-only
git log -1 --oneline                                  # the merge of chore/release-X.Y.Z
brain check --public --history                        # the stamp the push guard reads
git tag -a vX.Y.Z -m "brain X.Y.Z and research-graph X.Y.Z: what it brings"
git push origin vX.Y.Z
```

CI's `release-tag` job then checks that the tag, both `__version__` and the pin agree. Once it is green,
`brain update --check` on a machine at `vP` shows the new version and its `### Upgrade`. A tag is never moved: a
mistake is a new patch version.

## 4. The pin and the machines

A brain stays on its pin until it moves, so this is what releases the tag to a brain. Its `### Upgrade` section has the
steps for that version; in general:

- **A brain with an installer of its own** (`config.json` `engine.installer`): a PR in the brain that moves `engine.pin`
  to `vX.Y.Z`, with anything else its brain holds that names the version, and the rules that follow the engine's change
  (in the same PR, so that they never name a command the pin does not have). Run `brain sync` with the new engine, so the
  hooks it renders go in too. After its merge, on each machine: `<installer> -Apply` (its plan first), then restart
  the sessions.
- **A brain from `brain init`** (no `engine.installer`): `brain update` in the owner's terminal, then `y`. It installs
  the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. Then restart the sessions. An engine older
  than 0.2.6 runs that update and only reminds of the pin: run `brain update` once more.
- **Each public repo's checkout**: `brain check --public --history` before its next push. A stamp is valid only under
  the engine that made it, so an upgrade makes the push guard refuse the old one.

Tell anyone running a pilot of the tag, with the link to the section at that tag.
