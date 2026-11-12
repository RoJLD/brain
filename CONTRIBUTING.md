# Contributing

This repo is the public engine of the Brain: code, templates, examples and their docs. It holds two distributions
released together under one tag series, `research-graph` (`src/research_graph`, MIT, [`LICENSE`](LICENSE)) and the
`brain` command (`packages/brain`, Business Source License 1.1, [`packages/brain/LICENSE`](packages/brain/LICENSE)
and [`packages/brain/NOTICE`](packages/brain/NOTICE)). Read the licence of the part you change before you send a
change to it.

Nobody's own data lives here. A person's rules, decisions, backlog and memory stay in their own private repo; this
repo never names a private person, repo or project, and its tests and examples use invented ones (an owner named Ada, a
project named `lab`).

## Proposing a change

1. **Open an issue first** for anything beyond a small fix: what fails or what is missing, how to reproduce it, the
   version (`brain --version`) and the platform. A design change gets agreed in the issue before the code.
2. **Fork, then branch from `main`**: `feat/<slug>`, `fix/<slug>`, `docs/<slug>` or `chore/<slug>`. One subject per
   pull request.
3. **Change the code, its tests and its docs together**, in the same pull request:
   - a test for the behaviour you change, whenever one can be written (a regression test for a fix);
   - the docs it changes: [`README.md`](README.md), [`packages/brain/README.md`](packages/brain/README.md), the
     runbooks under `docs/` and `packages/brain/docs/`, a command's `--help` and usage lines;
   - one changelog fragment, never an edit of a `CHANGELOG.md`: `changes/<slug>.md` for `research-graph`,
     `packages/brain/changes/<slug>.md` for the `brain` command. Its first line names the section (`Added`, `Fixes`,
     `Changes`, or `Upgrade` for a step a user must take), then a blank line, then the entry
     ([`packages/brain/changes/README.md`](packages/brain/changes/README.md));
   - a persisted format, a schema or a CLI key is a public contract: your change reads what the last release
     wrote, and the last release reads back what your change writes (an unknown key tolerated, never an error; the
     `compat-prev` job below runs exactly that). Say in the pull request how your change keeps it, and add a
     `Compat:` line when a schema narrows ([`packages/brain/docs/formats.md`](packages/brain/docs/formats.md),
     « The schema diff »).
4. **Run the checks locally** (below), then open the pull request against `main`. Its description says what changes,
   why, and how it was tested.

A pull request is merged by the maintainer once its checks are green and its review is done. The maintainer may ask
for changes, split a pull request, or close one that does not fit the engine's scope.

## Style

- Python 3.10 or later; `research-graph` needs networkx and PyYAML, the `brain` command PyYAML and the standard
  library (its hooks run with the standard library only, in Git Bash on Windows).
- `ruff` with the root `pyproject.toml` (lines of 120 characters at most); no new dependency without an issue.
- English for code, docs, commits and pull requests. Plain sentences, no emojis.
- No secret, no personal data, no machine path of yours in a file, a test or a commit message.

## The checks a pull request passes

The CI (`.github/workflows/ci.yml`) runs on every pull request; a pull request is merged with every job that can
fail the run green.

| Job | What it runs | Fails the run |
|---|---|---|
| `test` | `ruff check src tests` and `pytest` for `research-graph`, on Linux, Python 3.10 to 3.12 | yes |
| `brain` | the `brain` command's suite on Windows, Python 3.10 and 3.12 (`pytest tests -n auto -m "not docker"` in `packages/brain`, then the docker tests) | yes |
| `release-check` | the changelog fragments (one malformed, a standard step asked twice); on a version pull request, the version policy | yes |
| `compat-prev` | the upgrade test: the last tag writes every registered format, this checkout is installed over it and reads it, then the tag reads back what this checkout wrote | yes |
| `harness-controls` | the upgrade test's negative controls, only when the harness, its fixtures or the workflows change | yes |
| `brain-linux` | the `brain` command's suite on Linux | advisory |
| `release-preview` | whether the next release would be a patch or a minor one, and why | advisory |
| `schema-diff` | what the schemas this pull request touches narrow | advisory |

Locally, from the repo's root:

```bash
pip install -e ".[test]"
ruff check src tests
pytest
```

```bash
pip install -e .
pip install --no-deps -e packages/brain
pip install pyyaml pytest "pytest-xdist>=3.5"
cd packages/brain
pytest tests -n auto -m "not docker"
```

Run the tests of the modules you touch first (`pytest tests/test_<module>.py`); the whole suite takes several
minutes. The `packages/brain` suite was first written on Windows: on Linux and macOS a few tests may still fail for
the platform (the `brain-linux` job is advisory for that reason).

Before the maintainer pushes, a second check runs on their side: `brain check --public --history` refuses a commit
that holds a private term of their brain, a secret, an e-mail address or a home folder. Keep your changes free of
them and it will pass.

## Releases and who signs them

Releases are cut by the maintainer, by the steps of [`docs/release.md`](docs/release.md): a version pull request
compiles the changelog fragments into each `CHANGELOG.md` and moves both versions, then a tag `vX.Y.Z` names both
distributions at that version.

- **A release tag is signed** (from v0.3.2 on) with an SSH ed25519 key of a person who holds the **`releaser` role**:
  a membership on the whole brain with `releaser` in its roles, in the releasing brain's `members.yaml`. Their signing
  keys that are not revoked are the release keys.
- **`allowed_signers`** is the file `git verify-tag` reads: one line per release key, valid for the namespace `git`
  only. It is generated from `members.yaml`, never edited by hand (`brain identity allowed-signers --write`), and is
  not published in this repo yet: publishing it is a separate decision, an export of that file
  ([`packages/brain/docs/identity.md`](packages/brain/docs/identity.md), « Signed releases »).
- **Who verifies**: `brain update` and the engine's installer run `git verify-tag` against the brain's
  `allowed_signers` before installing a tag. Nothing is refused by default; with `"engine": {"verify_tags": true}` in
  a brain's `config.json`, an unsigned tag, one signed by a key not in the file, or one that cannot be verified is
  refused. The CI's `release-tag` job checks that the tag, both versions and the pin agree, and only says whether
  the tag carries a signature.
- A contributor never tags, and a tag is never moved: a mistake is a new version.

## Reporting a security issue

Do not describe a vulnerability in a public issue (a guard that lets through what it should refuse, a secret that
could leak, a tag that installs without its check). Open an issue that says only that you have a security report,
without its details, and the maintainer will give you a private channel for the version and the steps to reproduce
it.
