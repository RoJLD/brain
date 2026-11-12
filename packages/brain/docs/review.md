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

The lenses are chosen from what the diff touches: **correctness** and **scope** always; **security** for a guard, a
hook, a secret or public path, the permissions; **compatibility** for a schema, a format, the state files, the registry
or a template; **install and upgrade** for the installer, `brain update` or the release; **procedure** for a procedure
or the rules; **tests** for the tests; **docs** for Markdown, the docs and the changelog fragments. A repo of a project
that declares `standards:` (projects.yaml) also gets a **standards** lens: one question per applicable `review-lens`
standard, does the change keep it (`brain standards lenses`, docs/standards.md).

The **scope** lens (`wi-brain-review-scope-lens`, the owner's TR-3 of 2026-11-11) asks what the item does not need:
a changed line beyond it, a refactor or a rename on the way, a flag or an option nobody asked for. Such a change leaves
the PR as a follow-up item (`brain item add`), unless the item cannot be done without it, which the finding's answer
says.

## 2. The agents, then the skeptics

1. One agent per lens, in parallel (the Agent tool or a workflow), each given the packet and asked for findings with
   a file, a line and a concrete failure scenario. Three or four lenses are enough; more is waste (RETRO-9).
2. Deduplicate: the same defect at the same place, from two lenses, is one finding.
3. Two skeptics per distinct finding, each asked to refute it. A finding both refute is dropped; one either upholds is
   kept.
   **The evidence rule** (TR-3): a negative claim, from a lens or a skeptic, such as « nothing calls it », « it is
   untested », « no other reader » or « never reached », stands only with the query that shows it (the grep, the
   `brain impact` or code-index call, the test run) and that query's coverage: what it searched and what it could not
   see (dynamic dispatch, another repo, a generated file). A clean result of a narrow query is no proof of absence; a
   negative claim without its query is unproven, and neither keeps nor refutes a finding on its own word.
4. Each kept finding is fixed with a test that fails before the fix, or contested with evidence in a PR comment. A
   scope finding is fixed by taking the change out of the PR into a follow-up item.

## 3. The stamp

```bash
brain review stamp <head> --findings N --fixed M --contested K --note review.md
brain review check <head>        # exit 0 once that head is reviewed
```

The stamp is keyed by the head's full sha, in `<BRAIN_HOME>/reviews/stamps/`: a push after the review is a new head,
reviewed again. Its counts are the error score's record (`wi-brain-review-error-score`), and `brain review check` is
the merge gate's question (`wi-brain-merge-gate`). With `--pr N` (or `--body FILE`) it also refuses while a
pinned decision the change touches is neither kept nor overridden in the PR body (`docs/pins.md`).
