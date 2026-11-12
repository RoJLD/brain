"""wi-brain-adr-target-check: a one-way-door ADR's Scope and Target compatibility, the register of future needs
computed from the graph, and the advisory checks (brain.targets; docs/adr-target.md)."""

import json
from pathlib import Path

import pytest

from brain import cli, docgraph, docjoin, notes, targets

LOG = """# Decisions

## 2026-01-02 — A format for the cups

**Context.** Cups need a format.

**Decision.** The cup file is YAML.

**Scope.** This lab, up to wave 0.2.0.

**Why.** It reads well.

**Target compatibility.**
- `feat-lab-mugs`: extension-point (a key added later)
- `wi-later`: compatible
- Leaves open: the mug's size.

**Revisit if.** a second kettle arrives.

## 2026-01-03 — A format written by hand

**Context.** x.

**Décision.** The pot file is JSON. Scope: this lab only. Target compatibility: wi-later (to review at 0.2.0);
ms-tea (compatible).

**Revisit if.** TODO

## 2026-01-04 — A two-way door

**Context.** x.

**Decision.** Meet on Mondays.

**Revisit if.** never.

## 2026-01-05 — A scope and nothing else

**Context.** x.

**Decision.** The spoon file is TOML. Scope: this lab.

**Revisit if.** spoons change.
"""


def _store(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "lab"
    store = root / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(
        "node_types: [WorkItem, Milestone, Feature, ADR]\n"
        "edge_types: [part_of, decided_by, depends_on]\n"
        "statuses: [todo, doing, blocked, done, pending, reached, planned, have, active]\n", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(
        "- {id: wave-0.1.0, type: Milestone, status: pending, title: Wave 0.1.0, props: {kind: wave, release: 0.1.0}}\n"
        "- {id: wave-0.2.0, type: Milestone, status: pending, title: Wave 0.2.0, props: {kind: wave, release: 0.2.0}}\n"
        "- {id: era-two, type: Milestone, status: pending, title: Era two, props: {kind: era}}\n"
        "- {id: ms-tea, type: Milestone, status: pending, title: First cup, props: {trigger: a cup at 95}}\n"
        "- {id: ms-done, type: Milestone, status: reached, title: Done, props: {trigger: old}}\n"
        "- {id: feat-lab-mugs, type: Feature, status: planned, title: Mugs, props: {module: K1}}\n"
        "- {id: feat-lab-cups, type: Feature, status: have, title: Cups, props: {module: K1}}\n"
        "- {id: wi-now, type: WorkItem, status: todo, title: Now, props: {module: K1}}\n"
        "- {id: wi-later, type: WorkItem, status: todo, title: Later, props: {module: K1}}\n"
        "- {id: wi-later-done, type: WorkItem, status: done, title: Later done, props: {module: K1}}\n"
        "- {id: wi-era, type: WorkItem, status: todo, title: In the era, props: {module: K2}}\n"
        "- {id: wi-k1, type: WorkItem, status: done, title: The cup format's item, props: {module: K1}}\n",
        encoding="utf-8")
    (store / "edges" / "work.yaml").write_text(
        "- {from: wi-now, to: wave-0.1.0, type: part_of}\n- {from: wi-later, to: wave-0.2.0, type: part_of}\n"
        "- {from: wi-later-done, to: wave-0.2.0, type: part_of}\n- {from: wi-era, to: era-two, type: part_of}\n"
        "- {from: wi-k1, to: adr-2026-01-02-a-format-for-the-cups, type: decided_by}\n"
        "- {from: wi-k1, to: adr-2026-01-05-a-scope-and-nothing-else, type: decided_by}\n", encoding="utf-8")
    log = root / "notes" / "decisions.md"
    log.write_text(LOG, encoding="utf-8")
    return root, store


def test_the_register_is_computed_from_the_graph(tmp_path):
    root, store = _store(tmp_path)
    needs = {n["id"]: n for n in targets.register(store, root)}
    assert sorted(needs) == ["feat-lab-mugs", "ms-tea", "wi-era", "wi-later"]   # not the current wave's, nor done
    assert needs["wi-later"]["phase"] == "wave-0.2.0" and needs["wi-era"]["phase"] == "era-two"
    assert needs["feat-lab-mugs"] == {"id": "feat-lab-mugs", "kind": "feature", "title": "Mugs", "phase": "later",
                                      "status": "planned", "native_status": "planned", "module": "K1"}


def test_fields_read_the_labels_and_the_sentences_an_adr_is_written_with():
    entries = {e["title"]: e["text"] for e in notes.adr_entries(LOG)}
    f = targets.fields(entries["A format for the cups"])
    assert f["Scope"] == "This lab, up to wave 0.2.0." and f["Revisit if"] == "a second kettle arrives."
    assert targets.cited(f["Target compatibility"], {"feat-lab-mugs", "wi-later", "ms-tea"}) == {
        "feat-lab-mugs": "extension-point", "wi-later": "compatible"}
    h = targets.fields(entries["A format written by hand"])
    assert h["Scope"] == "this lab only." and h["Revisit if"] == "TODO"
    assert targets.cited(h["Target compatibility"], {"wi-later", "ms-tea"}) == {"wi-later": "to-review",
                                                                               "ms-tea": "compatible"}
    assert targets.fields(entries["A two-way door"]).keys() == {"Revisit if"}


def test_the_checks_are_advisory_and_only_on_one_way_doors(tmp_path):
    root, store = _store(tmp_path)
    decs = targets.decisions(store, [root / "notes" / "decisions.md"], root)
    assert [d["id"] for d in decs] == ["adr-2026-01-02-a-format-for-the-cups", "adr-2026-01-03-a-format-written-by-hand",
                                       "adr-2026-01-05-a-scope-and-nothing-else"]   # the two-way door is not read
    assert decs[0]["modules"] == ["K1"] and decs[0]["file"] == "notes/decisions.md"
    found = sorted((f["id"], f["subjects"][0]) for f in targets.check(decs, targets.register(store, root)))
    assert found == [("decision.review-trigger-missing", "decision:adr-2026-01-03-a-format-written-by-hand"),
                     ("decision.target-compat-missing", "decision:adr-2026-01-05-a-scope-and-nothing-else"),
                     ("decision.target-unreferenced", "decision:adr-2026-01-05-a-scope-and-nothing-else")]


def test_target_text_and_its_refusal():
    assert targets.target_text(["feat-x=compatible", "wi-y=to-review:at 0.2.0"], "the size") == (
        "- `feat-x`: compatible\n- `wi-y`: to-review (at 0.2.0)\n- Leaves open: the size")
    with pytest.raises(ValueError, match="COMPAT one of"):
        targets.target_text(["feat-x=maybe"], "")


def test_brain_adr_new_writes_scope_and_target_and_adr_target_reads_them_back(tmp_path, monkeypatch, capsys):
    root, store = _store(tmp_path)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    (tmp_path / "projects.yaml").write_text(f"lab: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.chdir(root)
    argv = ["adr", "new", "A format for the saucers", "--context", "c", "--decision", "d", "--why", "w", "--revisit",
            "r", "--scope", "this lab", "--target", "feat-lab-mugs=compatible", "--leaves-open", "colours",
            "--date", "2026-01-06"]
    assert cli.main(argv) == 0
    text = (root / "notes" / "decisions.md").read_text(encoding="utf-8")
    entry = text.split("## 2026-01-06 — A format for the saucers")[1]
    assert "**Scope.** this lab" in entry and "**Target compatibility.**\n- `feat-lab-mugs`: compatible" in entry
    assert entry.index("**Scope.**") < entry.index("**Why.**") < entry.index("**Target compatibility.**") \
        < entry.index("**Revisit if.**")
    capsys.readouterr()
    assert cli.main(["adr", "new", "Half a door", "--context", "c", "--decision", "d", "--why", "w", "--revisit", "r",
                     "--scope", "s", "--date", "2026-01-07"]) == 0
    assert "fields left TODO: target" in capsys.readouterr().out
    assert cli.main(["adr", "new", "Bad", "--target", "x=perhaps"]) == 1
    assert cli.main(["adr", "target", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decisions"] == 5 and out["needs"] == 4
    assert cli.main(["adr", "target"]) == 0 and "target check: 5 one-way-door ADR(s)" in capsys.readouterr().out
    assert cli.main(["adr", "target", "--needs"]) == 0 and "feature   feat-lab-mugs (planned, later, K1): Mugs" in \
        capsys.readouterr().out


def test_the_register_joins_the_brains_document_and_the_join_runs_the_check(tmp_path):
    root, store = _store(tmp_path)
    doc = {"schema": docgraph.ID, "generated": {"at": "2026-01-01T00:00:00Z", "by": "t"},
           "nodes": [{"id": "decision:adr-2026-01-02-a-format-for-the-cups", "type": "decision", "title": "x",
                      "source": {"path": "notes/decisions.md"}}], "edges": [], "checks": [],
           "checks_run": ["doc.stale"], "checks_not_run": [c for c in docgraph.CHECK_IDS if c != "doc.stale"]}
    targets.add_to(doc, store, root, [root / "notes" / "decisions.md"])
    assert docgraph.validate(doc)[0] == []
    held = [n for n in doc["nodes"] if n["id"] == "decision:adr-2026-01-02-a-format-for-the-cups"]
    assert len(held) == 1 and held[0]["door"] == "one-way" and held[0]["module"] == ["K1"]   # merged, not twice
    assert {"from": "decision:adr-2026-01-02-a-format-for-the-cups", "to": "need:feat-lab-mugs", "type": "constrains",
            "compatibility": "extension-point", "origin": "derived",
            "source": {"path": "notes/decisions.md", "line": 3}} in doc["edges"]
    assert set(targets.PRESENCE) <= set(doc["checks_run"])
    j = docjoin.join([docjoin.Source("lab", "(emitted)", doc, emitted=True)], "t")
    unref = sorted(f["subjects"][0] for f in j["checks"] if f["id"] == "decision.target-unreferenced")
    assert unref == ["decision:lab/adr-2026-01-05-a-scope-and-nothing-else"]   # the cups' cites its K1 needs
    assert docgraph.validate(j)[0] == []


def test_the_join_never_checks_a_two_way_door_and_reads_a_declared_link():
    doc = {"schema": docgraph.ID, "generated": {"at": "2026-01-01T00:00:00Z", "by": "t"}, "nodes": [
        {"id": "need:n1", "type": "need", "title": "n", "phase": "S3", "status": "planned", "source": {"path": "x"}},
        {"id": "decision:a", "type": "decision", "title": "a", "source": {"path": "x"}},
        {"id": "decision:b", "type": "decision", "title": "b", "door": "two-way", "source": {"path": "x"}}],
        "edges": [{"from": "decision:a", "to": "need:n1", "type": "depends_on", "origin": "declared", "reason": "r",
                   "confirmed": True},
                  {"from": "decision:b", "to": "need:n1", "type": "depends_on", "origin": "declared", "reason": "r",
                   "confirmed": True}]}
    found = [f for f in docjoin.run_checks(doc) if f["id"] == "decision.target-unreferenced"]
    assert [f["subjects"] for f in found] == [["decision:a", "need:n1"]]
