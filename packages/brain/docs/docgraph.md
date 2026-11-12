# docgraph/v1: the documentation graph's contract

`docgraph/v1` is a public, versioned format for a documentation graph: the decisions, documents, milestones,
criteria, items, changes, tests, threats and modules of a project, the links between them, where each was read, and
the findings of a set of named checks. Any program may emit it: a repository's own docs command, built from its files
and its tracker alone; the Brain's doc graph, built from a brain's store; an import of documents kept elsewhere. The
Brain reads every `docgraph/v1` document read only, so a reader of several producers has nothing to translate.

The schema is [`schemas/docgraph.schema.json`](../src/brain/schemas/docgraph.schema.json); the rules a schema cannot
say are `brain.docgraph.validate`'s. Two invented documents, one of each side of the version, are in
[`tests/fixtures/formats/docgraph/v1/`](../tests/fixtures/formats/docgraph/v1/): a producer and a reader test against
the same files.

```bash
brain docgraph validate docs-graph.json     # exit 1 when it does not hold to the contract
brain docgraph checks                       # the named checks and what each means
```

Neither needs a brain: they run wherever the engine is installed.

## A document

```json
{
  "schema": "docgraph/v1",
  "generated": {"at": "2026-01-01T00:00:00Z", "by": "example-tool 0.1.0", "repo": "example-org/example",
                "ref": "0123abc", "sources": {"files": true, "tracker": "reachable"}},
  "nodes": [
    {"id": "decision:0005", "type": "decision", "kind": "adr", "title": "Encrypted transport between nodes",
     "status": "proposed", "native_status": "Proposed", "phase": "S2",
     "source": {"path": "docs/adr/0005-transport.md", "line": 1, "ref": "0123abc"}},
    {"id": "item:25", "type": "item", "title": "Signed orders", "status": "open", "phase": "S2",
     "source": {"tracker": "issue", "number": 25}}
  ],
  "edges": [
    {"from": "item:25", "to": "criterion:S2-13", "type": "serves", "origin": "derived",
     "source": {"tracker": "issue", "number": 25}},
    {"from": "decision:0008", "to": "decision:0007", "type": "contradicts", "origin": "declared",
     "reason": "a one-shot command against a service", "confirmed": false}
  ],
  "checks": [
    {"id": "criterion.no-item", "severity": "error", "subjects": ["criterion:S2-14"], "message": "no item serves it"}
  ],
  "checks_run": ["criterion.no-item", "cycle"],
  "checks_not_run": ["decision.modified-after-accept"]
}
```

| Key | Required | What |
|---|---|---|
| `schema` | yes | `docgraph/v1` |
| `generated` | yes | `at` (date-time) and `by` (the producer and its version), required; `repo`, `ref` (the commit read) and `sources` (what the producer could read, free keys) optional |
| `nodes` | yes | the nodes, below |
| `edges` | yes | the edges, below |
| `checks` | no | the findings of the checks the producer ran |
| `checks_run`, `checks_not_run` | no | the checks the producer ran (one with no finding passed), and the named checks its data does not allow it to run; never both for one check |

## Nodes

A node has an `id`, a `type`, a `title` and a `source`; `kind`, `status`, `native_status`, `phase`, `owner` and
`updated` are optional.

- **Ids** are `<type>:<native id>` (`decision:0005`, `item:25`, `document:docs/architecture.md#transport`), unique
  within the document. A reader of several documents namespaces them by project.
- **Types**. A producer emits the types it has, no more:

| Type | What | `kind` (examples) |
|---|---|---|
| `decision` | an ADR or a decision record | `adr`, `ddr`, `record` |
| `document` | a document or a section of one (`path#anchor`) | `tutorial`, `how-to`, `reference`, `explanation` (Diataxis), `generated`, `dated-spec` |
| `milestone` | a phase, a wave or an era | `phase`, `wave`, `era` |
| `criterion` | an exit criterion or a trigger line | |
| `item` | an issue or a work item | `review` for a phase's exit review |
| `change` | a pull request | |
| `test` | a test | |
| `threat` | a risk or a threat | |
| `module` | a module or a brick | |
| `owner-decision` | a dated decision of the owner made outside a decision record | |
| `finding` | a review finding | |
| `need` | a future need of a later phase (the register of needs); `phase` and `status` required | |

- **Statuses**, normalised: `proposed`, `accepted`, `superseded`, `open`, `closed`, `done`, `dropped`, `planned`,
  `stale`. The producer's own word goes in `native_status` (a need's « idea » is `proposed` with `native_status`
  `idea`).
- `phase` names the milestone the node belongs to, by its native id. `owner` is a role or a handle, never personal
  data. `updated` is when the node last changed (a date or a date-time), which `doc.stale` compares.

## Edges

An edge has `from`, `to`, `type` and `origin`.

| Type | From → to |
|---|---|
| `decided_by` | a node → the decision that settles it |
| `supersedes` | a decision → the one it replaces |
| `complements` | a decision → one it adds to |
| `depends_on` | an item (or a document) → what it needs first |
| `serves` | an item → a criterion |
| `part_of` | a criterion or an item → a milestone |
| `requires` | a decision or a criterion → a test |
| `carries` | an item → a test |
| `covers` | a test → a threat |
| `implements` | a change → an item; code → a module |
| `reports` | a decision or an owner's decision → the node that must contain it |
| `contradicts` | two nodes that cannot both hold, declared while nothing settles them (symmetric) |
| `documented_in` | a node → the document or section that cites it |
| `tested_by` | a node → a test |
| `constrains` | a decision → a need, with `compatibility`: `compatible`, `extension-point` or `to-review` |

- **`origin: derived`**: read from a citation; its `source` says where.
- **`origin: declared`**: stated by someone without a citation (a document that depends on another without citing it,
  a contradiction): its `reason` and `confirmed` (`false` while it is to be confirmed) are required.
- An edge may name an id the document does not hold (a dependency on another phase's item, a missing one): a reader
  keeps it, and `depends.cross-phase` reports it.

## Sources

Every node, and every derived edge, has a `source`: a file (`path` relative to the repository's root, `line`,
`anchor`) at a commit (`ref`), or a tracker object (`tracker`: `issue`, `pull`, `milestone`...; `number` or `url`). A
source names a `path` or a `tracker`.

## The named checks

Every producer and every reader mean the same thing by these ids (`brain docgraph checks` prints this table). A
producer runs the checks its data allows, lists the others in `checks_not_run`, and exits non-zero when it finds an
error. An id outside this list is the producer's own: a reader shows it without interpreting it. Every check id, a
named one or a producer's own, is lower case words joined by `-`, in dotted parts (`^[a-z][a-z0-9-]*(\.[a-z0-9-]+)*$`:
`example.own-check`).

| Check | Severity | Means |
|---|---|---|
| `criterion.no-item` | error | a criterion no item serves |
| `item.no-criterion` | warning | an item of a phase that has criteria serves none of them |
| `test.uncarried` | warning | a test no item carries |
| `test.carried-twice` | warning | a test two items or more carry |
| `threat.untested` | error | a threat no test covers |
| `depends.cross-phase` | warning | an item depends on an item of another phase that is closed or dropped, or on an id the document does not hold |
| `phase.review-incomplete` | warning | a phase's exit review (an item of kind `review` part of it) does not depend on every item of the phase |
| `cycle` | error | a cycle of `depends_on`, `part_of` or `supersedes` edges |
| `decision.modified-after-accept` | warning | an accepted decision whose text changed after it was accepted |
| `decision.number-unused-or-reused` | warning | a decision number skipped, or used by two decisions |
| `owner-decision.unreported` | error | a decision (or an owner's decision) whose `reports` edge reaches a node that does not cite it |
| `proposed.cited-as-decided` | warning | a node `decided_by` a decision that is still proposed |
| `doc.stale` | warning | a hand-written document whose cited node or declared parent changed after the document's last change; generated documents and dated specs are exempt |
| `decision.review-trigger-missing` | warning | a decision with no review section, or one with no precise trigger (a phase, a measure, an event) |
| `decision.target-compat-missing` | warning | a decision with no target compatibility section: the future needs it touches, each compatible, an extension point or to review, and what it leaves open |
| `decision.target-unreferenced` | warning | a decision that touches a need (a shared module or subject, or a declared link) without a `constrains` edge to it; it runs where the register of needs is |

The two `decision.*-missing` checks need only a repository's own decisions: a public repository can run them alone.
The compatibility section says what stays open; it never designs a later phase, and no check asks it to.

## Evolution

The status contract's rule (`brain.status/v1`, [formats.md](formats.md#external-formats)):

- an optional key may be added in v1 at any level, and a reader ignores the keys it does not know (the schema allows
  them everywhere);
- a key the schema names keeps its type and its values: a new node type, edge type, status, origin or severity, a key
  removed or retyped, or a change of meaning makes `docgraph/v2`;
- a reader refuses a later version with « a later contract than this engine's docgraph/v1: brain update », and judges
  none of its keys (their meaning may have changed).

## Neutral

A document holds no hostname, address, personal data or private name, and a public repository emits only what it
holds. What must stay private (documents kept elsewhere, an owner's coded decisions, review findings) is added by the
reader that joins several documents, in its own store, and never written back to the producer.

## What `brain docgraph validate` checks

The file is UTF-8 JSON (a byte order mark is accepted); a document nested too deep or holding a number too long to
read is refused as not JSON, never a crash. A top-level `v` is a producer's own key like any other: the version is
`schema`'s. Errors (exit 1): the schema's (a required key, a type, a value outside a list); a later version; an id used twice or
not prefixed by its type; a source that names no path and no tracker; a check both run and not run; a finding of a check
said not run. Notes (kept, never refused): an edge or a finding's subject that names an id the document does not hold,
a producer's own check (in a finding or in `checks_run`), an id in `checks_not_run` that is not a named check.
