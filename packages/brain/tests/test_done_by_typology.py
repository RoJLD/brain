"""The definition of done in two layers (wi-brain-done-by-typology, spec-brain-typology-packs E2, TYPO-1, TYPO-6): the
generic sentence for every item, then the clauses of its typologies (the software pack's: a PR, a test, the docs in
the same PR, the scout, the worktree); brain item close --evidence beside --pr, --pr required only for an item that
takes a PR clause (its props.typology, else its project's lifecycle.typologies; none declared: the rule before the
catalog, DONE-1). Fictitious names only."""

import json

import pytest
import yaml
from brain import cli, graph, projects, typologies


@pytest.fixture
def brain(store, monkeypatch):
    """The store fixture's root registered as the project demo; ``write(entry)`` sets its registry entry's extra
    lines."""
    root = store.parents[1]
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)

    def write(extra: str = "") -> None:
        (root / "projects.yaml").write_text(f"demo:\n  root: .\n{extra}", encoding="utf-8")
    write()
    write.root = root
    write.store = store
    return write


def _close(b, *args):
    return cli.main(["--root", str(b.root), "item", "close", *args])


def _props(b, nid):
    return graph.node_index(b.store)[nid][1].get("props") or {}


def test_the_catalog_holds_the_generic_sentence_and_the_clauses_of_software_and_research():
    cat = typologies.engine()
    assert typologies.self_check() == []
    assert [c.id for c in cat.done] == ["documented", "verified", "linked", "integrated", "recorded"]
    soft = [c.id for c in cat.clauses["software"]]
    assert soft == ["pr", "test", "same-pr-docs", "scout", "worktree"]
    assert [c.id for c in cat.clauses["research"]] == ["preregistered", "verdict", "reproducible"]
    assert set(cat.clauses) == {"software", "research"}   # the other kinds: named, not designed (TYPO scope)
    # a sub-profile takes its entry's clauses, once; two kinds stack; an unknown kind adds none
    ids = [c.id for c in cat.done_clauses(["cli", "service", "trading", "video-x"])]
    assert ids == ["documented", "verified", "linked", "integrated", "recorded", *soft,
                   "preregistered", "verdict", "reproducible"]
    assert [c.id for c in cat.done_clauses(["creation"])] == [c.id for c in cat.done]


def test_an_items_typologies_come_from_its_props_else_its_project():
    assert typologies.item_typologies({"typology": "creation"}, {"typologies": ["software"]}) == (
        ["creation"], "props.typology")
    assert typologies.item_typologies({"typology": "cli, research"}) == (["cli", "research"], "props.typology")
    assert typologies.item_typologies({}, {"typologies": ["strategy"]}) == (["strategy"], "lifecycle.typologies")
    assert typologies.item_typologies(None, None) == ([], "")
    cat = typologies.engine()
    assert [c.id for c in typologies.requires(cat, [])] == ["pr"]           # DONE-1: none declared, as before
    assert [c.id for c in typologies.requires(cat, ["cli"])] == ["pr"]
    assert typologies.requires(cat, ["strategy", "research"]) == []


def test_a_project_without_a_typology_still_closes_with_a_pr_only(brain, capsys):
    assert _close(brain, "wi-one", "--evidence", "a memo v2") == 2
    err = capsys.readouterr().err
    assert "no typology declared" in err and "--pr" in err and "merged by a pull request" in err
    assert _close(brain, "wi-one") == 2
    assert "--pr \"repo #N\" or --evidence" in capsys.readouterr().err
    assert _close(brain, "wi-one", "--pr", "demo #1", "--outcome", "shipped") == 0
    assert _props(brain, "wi-one")["pr"] == "demo #1"


def test_a_non_code_project_closes_with_evidence_and_a_software_item_in_it_with_a_pr(brain, capsys):
    brain("  lifecycle: {typologies: [strategy]}\n")
    assert projects.check(brain.root) == []
    assert _close(brain, "wi-one", "--evidence", "the go-to-market memo v3", "--evidence", "ddr-x") == 0
    props = _props(brain, "wi-one")
    assert props["evidence"] == "the go-to-market memo v3; ddr-x" and "pr" not in props
    graph.set_item(brain.store, "wi-two", ["typology=cli"])   # TYPO-6: an item that delivers code
    assert _close(brain, "wi-two", "--evidence", "a build") == 2
    assert "cli (props.typology)" in capsys.readouterr().err
    assert _close(brain, "wi-two", "--pr", "demo #2", "--evidence", "a build") == 0


def test_dropping_an_item_takes_any_evidence(brain):
    assert _close(brain, "wi-one", "--status", "dropped", "--evidence", "superseded by wi-two") == 0
    props = _props(brain, "wi-one")
    assert props["evidence"] == "superseded by wi-two" and "dropped" in props


def test_brain_item_clauses(brain, capsys):
    root = str(brain.root)
    assert cli.main(["--root", root, "item", "clauses", "wi-one"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("wi-one: no typology declared") and "[software] pr: merged by a pull request" in out
    assert "(brain item close --pr)" in out
    brain("  lifecycle: {typologies: [research]}\n")
    assert cli.main(["--root", root, "item", "clauses", "wi-one", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["typologies"] == ["research"] and data["source"] == "lifecycle.typologies" and data["requires"] == []
    assert [c["id"] for c in data["clauses"]][-3:] == ["preregistered", "verdict", "reproducible"]
    assert cli.main(["--root", root, "item", "clauses", "wi-nowhere"]) == 1


@pytest.mark.parametrize("entry, needle", [
    ("  lifecycle: [software]\n", "lifecycle is a mapping"),
    ("  lifecycle: {typologies: software}\n", "typologies is a list"),
    ("  lifecycle: {typologies: [video-x]}\n", "typology 'video-x' is not in the typology catalog"),
    ("  lifecycle: {colour: red}\n", "unknown key(s) colour"),
])
def test_a_bad_lifecycle_is_named(brain, entry, needle):
    brain(entry)
    assert any(needle in e for e in projects.check(brain.root)), projects.check(brain.root)


def test_the_other_lifecycle_keys_are_kept_as_declared(brain, monkeypatch):
    brain("  lifecycle: {typologies: [software], stage: build, shape: living, profile: internal}\n")
    assert projects.check(brain.root) == []
    assert projects.load(brain.root)["demo"].lifecycle["stage"] == "build"
    monkeypatch.setenv("BRAIN_STRICT", "0")
    brain("  lifecycle: {typologies: [video-x]}\n")
    assert projects.check(brain.root) == []   # read mode: a later catalog's id, noted
    data = yaml.safe_load((brain.root / "projects.yaml").read_text(encoding="utf-8"))
    assert data["demo"]["lifecycle"]["typologies"] == ["video-x"]   # kept as written
