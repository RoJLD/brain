# The review before the report

A session that opens a PR carrying code, a procedure, a hook, the installer, a schema or the engine's docs reviews it
itself, before it reports and before the PR merges (the owner's decisions RETRO-1, RETRO-2 and RETRO-9 of 2026-11-03,
`wi-brain-review-step`). A data PR of a brain (its graph, journal, decisions) gets the scripts only: `brain check` and
`brain audit --diff`.

## 1. The packet, at zero token

```bash
brain review prep 123            # a PR (gh), or BASE..HEAD; default origin/main..HEAD
```

It writes `<BRAIN_HOME>/reviews/<head>/` (or `--out DIR`):

| File | What it holds |
|---|---|
| `diff.patch` | the PR's diff against its merge base |
| `files/` | each touched file as it is at the head (a deleted, binary or very large one is listed, not copied) |
| `scout.txt` | `brain audit --diff BASE..HEAD`'s output (`--no-scout` leaves it out) |
| `packet.json` | the base, the head, the files and the lenses |
| `README.md` | the lenses and these steps |

The lenses are chosen from what the diff touches: **correctness** always; **security** for a guard, a hook, a
secret or public path, the permissions; **compatibility** for a schema, a format, the state files, the registry or a
template; **install and upgrade** for the installer, `brain update` or the release; **procedure** for a procedure or
the rules; **tests** for the tests; **docs** for Markdown, the docs and the changelog fragments. A repo of a
project that declares `standards:` (projects.yaml) also gets a **standards** lens: one question per applicable
`review-lens` standard, does the change keep it (`brain standards lenses`, docs/standards.md).

## 2. The agents, then the skeptics

1. One agent per lens, in parallel (the Agent tool or a workflow), each given the packet and asked for findings with
   a file, a line and a concrete failure scenario. Three or four lenses are enough; more is waste (RETRO-9).
2. Deduplicate: the same defect at the same place, from two lenses, is one finding.
3. Two skeptics per distinct finding, each asked to refute it. A finding both refute is dropped; one either upholds is
   kept.
4. Each kept finding is fixed with a test that fails before the fix, or contested with evidence in a PR comment.

## 3. The stamp

```bash
brain review stamp <head> --findings N --fixed M --contested K --note review.md --pr 123 --item ID
brain review check <head>        # exit 0 once that head is reviewed
```

The stamp is keyed by the head's full sha, in `<BRAIN_HOME>/reviews/stamps/`: a push after the review is a new head,
reviewed again. Its counts are the error score's record (`wi-brain-review-error-score`), and `brain review check` is
the merge gate's question (`wi-brain-merge-gate`). `--pr` names the PR (with the repo's `owner/name` from its origin
remote), so that a PR stamped on several heads counts once, by its latest stamp; `--item` names the item it delivers,
whose wave (`brain.waves`, in the repo's registered project) places the stamp, else `--wave X.Y.Z`; `--stream` the
lot or stream it belongs to.

### The note's finding lines

One line per confirmed finding, so that the score counts them by severity, lens and root cause at zero token:

```markdown
- high correctness A.b fixed: a rotation cut between two writes leaves a plain copy
- medium docs A.e contested: the runbook says the command refuses; it never did (a documented limit)
- low tests C fixed after covered: a test read the owner's git config; a script now refuses it
- low scope refuted: the rename is the item's own
```

The words before the colon, in any order (or as `key=value`): the **severity** (`high`, `medium`, `low`: required);
the **lens** (its first word: `correctness`, `scope`, `security`, `compatibility`, `install`, `procedure`, `tests`,
`docs`, `standards`); the **root-cause family** of the waves retro of 2026-11-03 (`A.a` data from before the change,
`A.b` failure and degraded paths, `A.c` an invariant held in one path only, `A.d` a contract assumed, `A.e` text
against code; `B` shared append points; `C` the environment; `D` the child-coordinator blind spots; `E` unsafe write
defaults; `F` hand-typed facts and coarse controls); the **outcome** (`fixed`, `contested`, `open`, `refuted`: a
refuted line is kept in the note but not counted); **when** it was found (`before` the merge, the default, or
`after`); whether a script now **covers** that family (`covered`, `uncovered`). A line with any other word before
its colon is prose, not a finding. `brain review stamp` says when the note's confirmed lines and `--findings` differ.

### The error score

```bash
brain review score               # every PR reviewed, the trend per wave, the rule's verdict
brain review score --wave 0.4.1 --json
```

Each PR counts once, by its latest stamp: its confirmed findings (`--findings`), and its finding lines by severity,
lens and root cause, those found after the merge and those a script now covers. Per wave, in release order, the
findings per PR. The owner's rule (2026-11-03): the reviews stay complete, three or four lenses and two skeptics per
finding, until the findings per PR fall over two waves in a row (the last three scored waves, each lower than the
one before); `brain review score` says which holds. `brain retro --wave W` prints the wave's score and the trend, and
the cockpit's health tab the totals, the last three waves and the verdict.
