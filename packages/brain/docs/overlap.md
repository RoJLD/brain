# The overlap check

A rule, a procedure step or a memory note written twice drifts: one copy is fixed, the other is not, and both are
injected into every session that reads them. `brain check`, in a brain's own root, warns when one of the brain's
texts restates another, at zero token. `brain.overlap`, `wi-brain-rule-overlap`.

```text
$ brain check
...
warning: overlap: memory/lab/release-steps.md:1 and source/procedures/release/SKILL.md:12 (2. Tag) share 64 % of
the smaller one's 8-word shingles (Jaccard 31 %): one text says it, the other points to it
```

It is a warning, never an error: `brain check`'s exit code does not change. The fix is a judgement: keep the text
in the one place it belongs and point to it from the other (a note's `[[link]]`, a procedure's « see rule-x »).

The method is agency-agents' originality check (`scripts/check-agent-originality.sh` in
[msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents), MIT), rewritten in Python and cut to the
size of a rule.

## What it reads

The Markdown files under `overlap.roots`, less those under `overlap.exclude` (globs relative to the brain's root):

| Key | Default | |
|---|---|---|
| `overlap.roots` | `<source>/rules/**/*.md`, `<source>/procedures/**/*.md`, `<memory>/**/*.md` | the neutral source's rules and procedures (`config.json` `source`), the memory notes (`config.json` `memory`) |
| `overlap.exclude` | `**/MEMORY.md` | the memory's index: one-line pointers to the notes |
| `overlap.warn` | `20` | the warning level, in percent |
| `overlap.min_shingles` | `10` | a smaller unit is not scored (about 17 words) |

A rendered copy is no root: a plugin's skills and rules, `AGENTS.md`, every file `brain render` writes repeats its
source on purpose and would match it at 100 %. Add a root only for text written by hand (`"roots": [..., "CLAUDE.md"]`
for a brain whose own `CLAUDE.md` holds rules).

## How two texts are compared

1. **Units.** A file is cut at its `## ` headings: each section is a unit (a rule of a rules file, a step of a
   procedure), and the text before the first heading another. A file without a heading (most memory notes) is one
   unit. Front matter, the heading's own line, HTML comments (a rule's `<!-- id: rule-x -->`) and URLs are
   left out.
2. **Neutral words.** Words are runs of letters, digits, `-` and `_`, lowercased. A word that holds a digit (a date, a
   PR number, a version), an id of three parts or more (`wi-lab-x`, `adr-2026-01-02-y`) or one of the brain's entity
   names (the owner, the projects of its registry, the terms of `public.deny` and those brain.denylist derives) is
   dropped; a compound word is split at its `-` and `_` (`zero-token` reads `zero token`). A copy that swaps an id, a
   date or a project's name still scores as a copy.
3. **Shingles.** Every run of 8 consecutive words of a unit is one shingle.
4. **The score.** For each pair of units of at least `overlap.min_shingles` shingles, the shingles they share over the
   smaller unit's: its **containment**. A note restated inside a longer rule scores high although the rule says more.
   The warning also gives the pair's Jaccard index (shared over the union), agency-agents' own score, which a long
   text dilutes. Two sections of one file are a pair too.

A pair at or above `overlap.warn` is one warning line. Since today's texts sit far below it (the calibration below),
a warning means a text new or changed since crossed it.

## The review's procedure lens

`brain review prep` adds the same lines, for the pairs a touched file takes part in, to the packet of a PR that calls
the **procedure** lens (a procedure, a rule or a `SKILL.md`): the lens sees what the change restates. They are read
from the checkout's files as they are on disk (`docs/review.md`).

## Calibration

The defaults were set on a real brain's texts before the check shipped (2026-11-24): 54 files (its rules, its five
procedures, 47 memory notes), 114 units, 6 441 pairs. 8 pairs share a shingle at all; every other pair shares none.

| score | max | the 8 pairs sharing a shingle | pairs at 20 % or more |
|---|---|---|---|
| containment, per unit | 8.3 % | 8.3, 4.5, 1.0, 0.6, 0.6, 0.4, 0.4, 0.2 % | 0 |
| Jaccard, per unit | 0.8 % | | 0 |
| Jaccard, per whole file (agency-agents' way) | 0.4 % | | 0 |

agency-agents reports the same baseline on its own library (worst pair about 1.5 % Jaccard) and warns at 20 %, fails
at 40 %. The texts agree: a warning at 20 % sits at 2.4 times the worst pair of today, and the worst pair is a shared
sentence, no restated rule.

The check was then replayed on copies made from those texts: each unit, or a contiguous half or third of it pasted
into another file's unit, with its digits, ids and entity names swapped and a share of its words replaced at random.
The share caught at each level:

| copy | words changed | at 20 % | at 30 % | at 40 % | at 50 % |
|---|---|---|---|---|---|
| whole unit | 0 % | 100 % | 100 % | 100 % | 100 % |
| whole unit | 6 % | 100 % | 100 % | 96 % | 88 % |
| whole unit | 10 % | 95 % | 87 % | 62 % | 32 % |
| half, in another unit | 0 % | 97 % | 95 % | 88 % | 35 % |
| half, in another unit | 6 % | 88 % | 46 % | 19 % | 4 % |
| a third, in another unit | 0 % | 93 % | 54 % | 19 % | 11 % |
| a third, in another unit | 6 % | 50 % | 17 % | 9 % | 3 % |

The rendered copies of the same brain (its plugin's skills and rules, its `AGENTS.md`) all score 100 %, which is why
they are no root.

## Its limits

- It sees copies, not paraphrases: a rule said again in other words shares no 8-word run. `brain rules diff` (the
  README, « The rules across their sources ») compares the rules a session reads by content words, and computes
  contradictions.
- It reads only the brain's own roots, at the root `brain check` runs in, not with `--all`.
- An error level (`overlap.fail`, agency-agents' 40 %) is for a later slice, once the warnings have been lived with.
