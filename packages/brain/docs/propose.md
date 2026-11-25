# The wave composer: `brain wave propose`

`brain wave propose [--waves N] [--from WAVE] [--items N] [--points N] [--at-once N] [--no-merged] [--against FILE]
[--all] [--json]` drafts the next N waves at zero token (`brain.propose`, wi-brain-wave-propose). It prints a proposal,
writes nothing and refuses nothing: the coordinator composes the waves from it (`brain wave add`, `brain item link ID
part_of WAVE`, `brain wave plan`) and answers its questions.

## What it reads

| Input | Source |
|---|---|
| the open items, their status, priority, size, props | the store (brain.waves) |
| merged but not closed | brain.closemerged's mapping (`brain.lots.merged_of`, git only): counted done, never a candidate; `--no-merged` reads none |
| depends_on | the store: an item after its open prerequisites |
| placements | brain.placement ([placements.md](placements.md)): pinned, a choice, earliest, latest, before or after an era's stage, with an item, its own lot, out |
| the rank | brain.ranking: the owner's priority, the owner's order, value over effort |
| points | the size: S 1, M 2, L 4, XL 8 (none: M) |
| the capacity | `--items` and `--points`, else the median of what the last 3 reached waves closed (their done items and points), else 12 items and 32 points |
| the lots | brain.lots' cutter (weighted surfaces, hot files, lot and chain caps), then gathered into 6 sessions at most |

## How it fills

1. **Out first**, each with its reason: a blocked item, an external blocker, a placement out (owner, later, a
   trigger), « after 1.0 » with no wave named, a pin beyond the drafted waves, a `depends_on` cycle (also a question).
2. **The windows** are the N waves after `--from` (default: the last pending wave), by their place `sN`; the release
   of each is the next patch after the one before, a minor when it holds a one-way door (`props.door`,
   `props.one_way_door`, or « one-way door » in its `size_reason`). A window that is a pending wave already composed
   (`--from` an earlier wave) keeps its composed items: they count against its capacity and are listed (`why`:
   `composed`).
3. **Wave by wave**: the items pinned to it (over the capacity if need be: a question); then, first, the items whose
   pin or choice names only waves already composed without them, those due by a wave before the drafted ones, the
   items a composed item waits on, and the open prerequisites of all of these; then those due (a latest wave, « before
   1.0 »); then by rank. An item goes in when its placement allows the wave (its pin; one of the waves of its choice;
   from its earliest), every open `depends_on` prerequisite is placed earlier or in the same wave within a chain of 3,
   every open item it is placed `after` is in an earlier wave, and the capacity holds. After each item placed the
   order is read again from the top, so an item first in order whose prerequisite has just come in takes its place
   before lower-ranked ones. A latest wave orders, never excludes: a deadline missed (no room by then, or already
   past) is drafted as early as it can be and asked. About a fifth of the places wait for quick wins (size S, high
   value) and go to the rest when none comes. An item placed `with` another brings it along when it can (a partner
   done, merged or standing needs nothing; one out is said with its reason). A standing item (`props.standing`, a
   debt item's `props.audit_repo`) is a batch in every wave.
4. **The lots**: each wave's items cut by `brain wave plan`'s cutter, an `own-lot` item alone (when the rest of its
   lot would both wait on it and be waited on by it, the rest is cut in two: what it waits on, and the others), lots
   that share no file gathered by module, then by size, into 6 at most (8 items a lot), never two lots joined when
   one reaches the other through a third (a cycle between lots), in rounds by their `depends_on`.

## What it says

Per wave: its id, release and kind, its items against the capacity, its doors (each an ADR with Scope and Target
compatibility), its standing batches, its lots by round, what waits on the owner (`open`, `external_blocker`, pending
DDRs), its exit (the items merged, the tag). Then the eras (the items due before each exit: placed, left), the items
left out with their reason (capacity, dependency, window, owner, later, trigger, external, blocked; the first 20, `--all`
for every one), the questions (an item that comes first says, once the fill is done, the wave it was drafted in or
why it is in none), the checks (an item before a prerequisite or in the wave of an item it is placed `after`, an item
twice, a pin or a choice not honoured: empty when the draft holds) and the risks (unchecked lots, a wave over its
capacity, uncalibrated sizes). `--against FILE`, an earlier `--json`, says what moved in each wave; a file of another
shape is refused with one line (exit 1).

`--json` is versioned (`format` 1, keys only added): `format`, `from`, `capacity`, `waves` (`seq`, `id`, `release`,
`kind`, `items`, `standing`, `lots`, `rounds`, `doors`, `size`, `waits`, `exit`), `out`, `questions`, `checks`,
`merged`, `eras`, `risks`, `diff`.

## Limits

Judgement stays with the coordinator and the owner: a wave's theme, value beyond priority and unblock counts, « before
or after 1.0 », the owner's availability. Placements are read, never guessed (placements.md). Sizes are judgement and
the points estimates. Surfaces are predictions: a lot with no known surface is unchecked. The era's gates and a
`--apply` that writes the waves are extension points, not part of this command. The inflow makes a proposal stale
within days: it is a draft per composition, not a roadmap of record.
