"""Small graphs and a fake git history for the backlog, roadmap and decisions queries (research_graph.query,
history, roadmap, priorities; acme backlog). Everything is built under tmp_path: no test reads the real graphs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCHEMA = """\
owner: Ada
node_types: [WorkItem, Milestone, Spec, ADR, Experiment]
edge_types: [depends_on, part_of, specified_by, decided_by, delivers]
statuses: [todo, doing, blocked, done, dropped, pending, reached, proposed, active, superseded, open]
layers:
  work: [WorkItem, Milestone, Spec]
  decisions: [ADR]
  research: [Experiment]
status_by_type:
  WorkItem: [todo, doing, blocked, done, dropped]
  Milestone: [pending, reached, dropped]
  Spec: [proposed, active, superseded]
  ADR: [active, superseded]
"""

WORK = """\
# work layer of the fixture
- {id: spec-draft, type: Spec, status: proposed, title: "Draft spec", anchor: "docs/specs/2026-10-01-draft.md#top"}
- {id: spec-live, type: Spec, status: active, title: "Validated spec", anchor: "docs/specs/2026-09-01-live.md#top",
   props: {validated: "2026-09-02 by Ada"}}
- {id: spec-gov, type: Spec, status: active, title: "Governance", anchor: "docs/specs/2026-10-20-gov.md#top",
   props: {validated: "2026-10-21", open: "Q3 (command shape)"}}
- {id: ms-top, type: Milestone, status: pending, title: "Top", props: {trigger: "all done"}}
- {id: ms-sub, type: Milestone, status: pending, title: "Sub"}
- {id: ms-old, type: Milestone, status: reached, title: "Old", props: {trigger: "t", reached: "2026-09-15: evidence"}}
- {id: ms-older, type: Milestone, status: reached, title: "Older", props: {reached: "2026-08-01: earlier"}}
- {id: wi-doing, type: WorkItem, status: doing, title: "Doing item", props: {priority: P1, repo: ops-repo}}
- {id: wi-todo, type: WorkItem, status: todo, title: "Todo after doing",
   props: {priority_proposed: P2, priority_reason: "after wi-doing", spec: spec-draft}}
- {id: wi-free, type: WorkItem, status: todo, title: "Free item about funding",
   props: {pr: "acme-data #16", after: "wi-doing stage 1"}}
- {id: wi-ext, type: WorkItem, status: blocked, title: "Waits on Ada",
   props: {external_blocker: "Ada decides", open: "which venue"}}
- {id: wi-ext2, type: WorkItem, status: blocked, title: "Waits on the cluster",
   props: {external_blocker: "the cluster is not there", note: "moves ms-top"}}
- {id: wi-prereq, type: WorkItem, status: todo, title: "Prerequisite outside the milestone", props: {note: "see ms-top"}}
- {id: wi-done-dated, type: WorkItem, status: done, title: "Closed with a date",
   props: {pr: "research-lab #5", done: "2026-10-20: shipped it"}}
- {id: wi-done-undated, type: WorkItem, status: done, title: "Closed without a date"}
- {id: wi-dropped, type: WorkItem, status: dropped, title: "Dropped", props: {done: "2026-10-10 replaced by wi-free"}}
- {id: adr-1, type: ADR, status: active, title: "A decision"}
- {id: exp-1, type: Experiment, status: open, title: "Funding experiment"}
"""

EDGES = """\
- {from: wi-todo, to: wi-doing, type: depends_on}
- {from: wi-todo, to: spec-draft, type: specified_by}
- {from: wi-doing, to: ms-sub, type: part_of}
- {from: wi-todo, to: ms-sub, type: part_of}
- {from: ms-sub, to: ms-top, type: part_of}
- {from: wi-done-dated, to: ms-top, type: part_of}
- {from: wi-doing, to: wi-prereq, type: depends_on}
- {from: wi-done-undated, to: ms-old, type: part_of}
- {from: wi-ext, to: adr-1, type: decided_by}
"""

DRAFT_SPEC = """\
# Draft

## 5. Open questions

1. **Cadence**: daily or hourly?
   A second line of the same question.
2. **Scope**: which venues?
   Décision : Bybit first (Ada, 2026-10-02).
3. Mirror the store?

## 6. Order

1. Not a question.
"""

GOV_SPEC = """\
# Governance

## 7. Questions pour Ada

**Q1. Visibility.** *(one choice)*
- [ ] **A. Public** *(recommended)*
- [ ] B. Private

**Q2. Storage.**
- [x] A. NAS
- [ ] B. Cloud

**Q3. Command shape.**
- [ ] A. one

## 8. Décisions de Ada (2026-10-21)

| # | Décision |
|---|---|
| Q1 | **A** : public |
| Q3 | **Ouverte**, reformulée ci-dessous |

**Q3, reformulée : one command or one per project?** *(one choice)*
- [ ] A. one

Questions qui restent :
- which database?

```text
1. not a question either
```

## 9. Questions initiales (pour mémoire)

1. An old question kept for the record.
"""

BRAIN_WORK = """\
- {id: wi-brain-x, type: WorkItem, status: todo, title: "Brain item", props: {priority: P0}}
- {id: ms-brain, type: Milestone, status: pending, title: "Brain milestone", props: {trigger: "x"}}
- {id: adr-1, type: ADR, status: active, title: "The Brain's own adr-1 (same id as Acme's)"}
"""


def write_store(repo: Path, work: str = WORK, edges: str = EDGES, *, specs: bool = True) -> Path:
    """A repo with notes/graph (schema, nodes/work.yaml, edges/work.yaml) and the specs the nodes anchor."""
    store = repo / "notes" / "graph"
    (store / "nodes").mkdir(parents=True, exist_ok=True)
    (store / "edges").mkdir(parents=True, exist_ok=True)
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("[]\n", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(work, encoding="utf-8")
    (store / "edges" / "work.yaml").write_text(edges, encoding="utf-8")
    if specs:
        spec_dir = repo / "docs" / "specs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "2026-10-01-draft.md").write_text(DRAFT_SPEC, encoding="utf-8")
        (spec_dir / "2026-10-20-gov.md").write_text(GOV_SPEC, encoding="utf-8")
    return store


def write_brain(root: Path) -> Path:
    """my-brain-like checkout: <root>/notes/graph with its own items and an id that clashes with Acme's."""
    return write_store(root, BRAIN_WORK, "- {from: wi-brain-x, to: ms-brain, type: part_of}\n", specs=False)


# ---------------------------------------------------------------- fake git history


def git(repo: Path, *args: str, day: str | None = None) -> str:
    env = dict(os.environ)
    if day:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{day}T12:00:00+00:00"
    res = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                          "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _item(nid: str, status: str, title: str | None = None, props: str = "") -> str:
    p = f", props: {{{props}}}" if props else ""
    return f"- {{id: {nid}, type: WorkItem, status: {status}, title: \"{title or nid}\"{p}}}\n"


def make_history(tmp_path: Path) -> Path:
    """A repo whose main has five first-parent steps:

    2026-10-01  A  wi-a, wi-b, wi-gone todo (work.yaml), wi-c todo (other.yaml), ms-1 pending
    2026-10-04  #7 merge of feat (commits of 10-02 and 10-03): wi-a todo -> doing, then props +pr
    2026-10-05  D  wi-b done and retitled, wi-c moved to work.yaml (no event), wi-gone removed, wi-d created
    2026-10-06  E  work.yaml does not parse (skipped)
    2026-10-07  F  work.yaml fixed, wi-d todo -> doing
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    store = write_store(repo, "", "", specs=False)
    nodes = store / "nodes"
    ms = "- {id: ms-1, type: Milestone, status: pending, title: m1}\n"

    def commit(msg: str, day: str) -> None:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg, day=day)

    (nodes / "work.yaml").write_text(ms + _item("wi-a", "todo") + _item("wi-b", "todo") + _item("wi-gone", "todo"),
                                     encoding="utf-8")
    (nodes / "other.yaml").write_text(_item("wi-c", "todo"), encoding="utf-8")
    commit("A: seed", "2026-10-01")
    git(repo, "checkout", "-q", "-b", "feat")
    (nodes / "work.yaml").write_text(ms + _item("wi-a", "doing") + _item("wi-b", "todo") + _item("wi-gone", "todo"),
                                     encoding="utf-8")
    commit("B: start a", "2026-10-02")
    (nodes / "work.yaml").write_text(ms + _item("wi-a", "doing", props='pr: "research-lab #7"') + _item("wi-b", "todo")
                                     + _item("wi-gone", "todo"), encoding="utf-8")
    commit("C: pr of a", "2026-10-03")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "feat", "-m", "Merge pull request #7 from RoJLD/feat", day="2026-10-04")
    work_d = (ms + _item("wi-a", "doing", props='pr: "research-lab #7"') + _item("wi-b", "done", "b, renamed")
              + _item("wi-c", "todo") + _item("wi-d", "todo"))
    (nodes / "work.yaml").write_text(work_d, encoding="utf-8")
    (nodes / "other.yaml").write_text("", encoding="utf-8")
    commit("D: close b, move c, drop gone, add d", "2026-10-05")
    (nodes / "work.yaml").write_text(work_d + "- {id: broken\n", encoding="utf-8")
    commit("E: broken yaml", "2026-10-06")
    (nodes / "work.yaml").write_text(work_d.replace("wi-d, type: WorkItem, status: todo",
                                                    "wi-d, type: WorkItem, status: doing"), encoding="utf-8")
    commit("F: fix yaml, start d", "2026-10-07")
    return repo
