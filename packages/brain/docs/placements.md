# Placements: where an item may go among the waves

`brain.placement` (wi-brain-placement-grammar) reads where each open work item may go among the waves, at zero
token, for `brain wave placements` and for the wave composer. A placement is a set of constraints on an item's wave,
resolved to wave places: the N of `wave-sN`, a legacy wave's place in the order, and a future wave's N even before the
wave exists.

## Two sources

1. **`props.place`**, the structured placement (format v1, below). It is authoritative: when an item has one, its free
   text is not read for placement. The free text stays as written, for people.
2. **The free text** the owner's placements were recorded in, read for its placement words only:
   - `props.wave_planned`, `props.planned_wave`, `props.wave_fit`, `props.wave` (in that order; the first that names a
     wave holds the pin);
   - `props.after_1_0`: item ids, an ordering that binds only after the 1.0 era's exit; a value that names no item is
     unparsed, listed, and an id shaped like the store's items that is not there is said;
   - the `decided_*` answers, newest first, read only for a wave `sN` (named, or « after sN », « before sN », « sN or
     later »: its bounds), « the wave after X.Y.Z », « before 1.0 », « after 1.0 », « unplaced » and « later ». A
     release an answer names is a fact (« after 1.0.0 shipped »), not a wave nor a bound. An answer's waves and bounds
     are not read when a placement text above already was: an answer that names a wave beside it speaks of something
     else (a slice, a sibling);
   - `props.track`: « owner » takes the item out of the waves.

   A phrase it does not know is never guessed: an item whose placement text yields nothing is **unparsed**, listed
   with its text. Parentheses are provenance (a decision's code, a date, an ADR id, a path): only their « proposed » and
   « later » are read, and « proposed » only beside a placement read. A wave is named in lower case, alone: `S1-S3`
   are slices, `roadmap-s8-s12.md` is a path, `s11.md` a file name and `wave-close` a command (a wave id holds a
   digit). « s4 or s5 » and « s4/s5 » are a choice, « s4 or later » is `earliest s4`, « s5 or earlier » `latest s5`.
   « after wi-x » names an item: one that is not there is said (« names no item »), never read as a trigger; a
   hyphenated word (« after long-term planning ») is one. Several triggers are kept together, joined by « , ».

## `props.place`, format v1

Clauses separated by `;`, each a keyword and its arguments. A wave is named by its place `sN`, its id or its release
`X.Y.Z`; a stage `X.Y` is an era's `props.stage_to` (« 1.0 »).

| Clause | Means |
|---|---|
| `v1` | the format (optional, first) |
| `wave s11` | pinned to that wave |
| `wave s11 or s12` | a choice: put as a question, the earlier wave by default |
| `earliest s11`, `latest s12` | bounds |
| `before 1.0` | due before that era's exit; `before s12` is `latest s11` |
| `after 1.0` | not before that era's exit; `after s10` is `earliest s11` |
| `after wi-a, wi-b` | after those items' waves |
| `after wi-a past 1.0` | that ordering binds only after that era's exit (`props.after_1_0`) |
| `with wi-c` | in the same wave |
| `own-lot` | a lot of its own |
| `round 2` | the round it was planned in |
| `proposed` | a soft placement: the composer may move it |
| `unplaced` | no constraint: the composer places it |
| `out owner`, `out later`, `out trigger: <why>` | out of the waves, with its reason |

An unknown clause is listed (a `brain check` warning) and the others are read, so a newer brain's additive clause is
not lost. A first clause `v2` or above (`V2` too) is not read at all: the item is listed, « written by a newer brain »;
a composed item keeps its wave's pin. One placement holds one `before` stage, one `after` stage and one stage past
which its orderings bind: a second, different one is listed and not read. `out later` beside a wave keeps both and is
put as a question. `round` takes ASCII digits. A clause
that changes meaning bumps `v` (docs/formats.md). `brain item set ID place="wave s11; after wi-a; own-lot"` writes one;
`brain wave placements` prints each item's placement in this form, ready to copy.

## What it resolves

Each open item gets one placement, with its status:

| Status | Means |
|---|---|
| composed | in a pending wave now (`part_of`, or `carried_to`): the plan's fact; its text is history, its pin that wave |
| pinned | a wave named |
| choice | two waves or more named: a question |
| constrained | bounds, a stage, items it comes after or with, its own lot; no wave |
| free | parsed, no constraint (« unplaced », « placed at its composition », a stale pin) |
| out | owner, later or a trigger (« after calibration », « when a project needs it ») |
| unparsed | placement text, nothing read |
| none | no placement text |

What cannot be honoured is said, never dropped: a pin on a wave already reached or dropped (`stale`; the item is
overdue, not pinned: a question), a release or an item named that is not there, two waves or two choices in one text,
two sources that disagree (the first one read wins), a pin before its earliest or after its latest wave, an earliest
wave after the latest, a wave beside `out later`; a free text's « later » beside a wave it names is a note (the wave
is read). The questions (`Placement.questions()`, `--json`'s `questions`) are the conflicts, a choice, the stale pins
and the names of no wave or item. `Placement.constraints()` gives the
composer its rules: `pin`, `choice`, `earliest`, `latest`, `before_era`, `after_era`, `after`, `together`, `own_lot`,
`out`.

## `brain wave placements --json`

`format` 1, keys only added: `format`, `place_v`, `counts` (by status), `items` (each: `id`, `status`, `wave`, `pin`,
`choice`, `earliest`, `latest`, `before`, `after_stage`, `era`, `after`, `soft_after`, `soft_stage`, `together`,
`own_lot`, `round`, `soft`, `out`, `why`, `source`, `texts`, `stale`, `notes`, `conflicts`, `canonical`), `questions`.
