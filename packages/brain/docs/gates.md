# Gates as data

(`wi-brain-forecast-gates`; the code is `brain/gates.py`, read by `brain forecast`, `brain check` and `brain queue`.)

A gate holds a node without being work: data to accumulate, a counter to reach, another project's item, a machine to
come, a Go/NoGo. Written in prose (« 4 weeks in a row », « at least 100 answered DDRs », « once gpu-box is here »),
it makes every forecast optimistic. Written as data, the forecast draws it, `brain check` judges it and the owner's
queue counts what it holds.

## The format

A WorkItem or a Milestone carries `props.gate`: one gate, or a list of them. Each is a mapping with a `kind`; an
entry in prose is kept as a malformed gate, which holds its node until it is written as data:

| kind | fields | the forecast draws |
|---|---|---|
| `calendar` | `days: N`; `from:` a date `YYYY-MM-DD`, an item id or a milestone id (today without it: a count that never passes, `brain check` says so); `resets:` the rule in words; `reset_daily:` the chance a day resets the count (0 <= p < 1) | the days left from now; counted from an open item, from that item's own end (it becomes a dependency); from a done item or a reached milestone, from its `done` or `reached` date (without it, or from a dropped node, not dated); each reset starts the whole count again |
| `count` | `of:` a counter, `at_least: N`; `current:` and `per_day:` for a counter the engine does not measure | the days the counter needs at its pace |
| `external` | `ref: <project>:<id>` | nothing: passed once that item is done, otherwise not dated (the joint simulation of projects is wi-brain-scope-rollups') |
| `hardware` | `machine: <name>`; `ready:` a day or a range, `2026-12..2027-01` (a month spans its days) | a day drawn within the range; without `ready`, not dated |
| `go_nogo` | `ddr: <id>` (optional) | a lag drawn from the owner's past answer delays once the node's dependencies are done (its exit evidence met); passed once that DDR is answered |

The counters the engine measures: `ddr.answered` (the answered DDRs of `records/ddr`, their pace over the last 28
days) and `items.done` (the store's done items, their pace from the store's history).

```yaml
- {id: ms-learned-harness, type: Milestone, status: pending, title: "...", props: {trigger: "100 answered DDRs",
   gate: {kind: count, of: ddr.answered, at_least: 100}}}
- {id: wi-capture-month, type: WorkItem, status: todo, title: "...", props: {
   gate: [{kind: calendar, days: 30, from: wi-capture, resets: "a missed day", reset_daily: 0.02},
          {kind: hardware, machine: gpu-box, ready: "2026-12..2027-01"}]}}
```

Two gates need no prop:

- a pending **blocking** DDR whose `links.items` names an item: the owner's decision, drawn from their past answer
  delays;
- a pending DDR of kind **action** that names an item (what only the owner may do, blocking or not): drawn from the
  delays of the actions done (asked to answered), the answer delays while none is done.

## Deadlines

`props.due` is not a gate but a deadline: only a real external date (a pilot, a legal step, hardware, a third party),
with its `due_source`. The forecast raises an alert when an item's p80 passes it (`ALERT` under its inputs,
`gates.late` in `--json`); elsewhere the wave is the timebox and the p80 a soft date.

## What reads them

- `brain forecast`: each future draws every gate; an item waits for its latest release, a milestone for its own gate
  too. A gate it cannot date (hardware without `ready`, a count without a pace, another project's open item) leaves
  the item, and what waits on it, not dated, with the reason. The inputs list each declared gate, its state (drawn,
  undated, passed) and what it holds. The model is v2.
- `brain check` warns on a malformed gate, on one the forecast cannot date as written (a calendar without `from`,
  from a node that never ends, a hardware range already over), on a trigger that names a duration (days, weeks, in a row, consecutive)
  on a node with no gate, on an `after_external` (or an external gate) that does not resolve to `<project>:<id>`
  (a registered project, an id of its store), and on a `due` without its `due_source`. Warnings only.
- `brain queue` ends with what each gate holds, downstream included: « hardware gpu-box holds 3 milestone(s) »; a gate
  that passed or is malformed holds nothing there.
