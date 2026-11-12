"""wi-brain-docgraph-read: the docgraph/v1 documents of the projects a brain only reads, pinned at a commit, joined
with the brain's own documents under namespaced ids, and the named checks run again across the joined graph
(brain.docjoin; docs/docgraph.md, « Reading several documents »)."""

import json
import subprocess
from pathlib import Path

from brain import cli, docgraph, docjoin

FIXTURES = Path(__file__).parent / "fixtures" / "formats" / "docgraph" / "v1"
GEN = {"at": "2026-01-01T00:00:00Z", "by": "example-tool 0.1.0"}


def _doc(nodes, edges=(), checks=()):
    return {"schema": docgraph.ID, "generated": dict(GEN), "nodes": list(nodes), "edges": list(edges),
            "checks": list(checks)}


def _n(nid, title="x", **kw):
    return {"id": nid, "type": nid.split(":", 1)[0], "title": title, "source": {"path": "docs/x.md"}, **kw}


def _e(a, b, t, **kw):
    return {"from": a, "to": b, "type": t, "origin": "derived", "source": {"path": "docs/x.md"}, **kw}


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          timeout=60).stdout.strip()


def _registry(tmp_path, monkeypatch, store):
    root = store.parents[1]
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\nupstream:\n  title: a project the brain reads\n"
                   "  access: read\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


def _clone(tmp_path, doc) -> tuple[Path, str]:
    """A repository holding ``doc`` at docs/docs-graph.json, committed: (its path, the commit)."""
    up = tmp_path / "upstream-clone"
    (up / "docs").mkdir(parents=True)
    _git(up, "init", "-q", "-b", "main")
    _git(up, "config", "user.email", "t@example.org")
    _git(up, "config", "user.name", "t")
    (up / "docs" / "docs-graph.json").write_text(json.dumps(doc), encoding="utf-8")
    _git(up, "add", "-A")
    _git(up, "commit", "-q", "-m", "graph")
    return up, _git(up, "rev-parse", "HEAD")


# --- pinning ----------------------------------------------------------------------------------------------------------

def test_pin_copies_a_read_projects_document_at_a_commit_and_never_touches_the_clone(tmp_path, monkeypatch, store):
    root = _registry(tmp_path, monkeypatch, store)
    src = json.loads((FIXTURES / "older.json").read_text(encoding="utf-8"))
    up, sha = _clone(tmp_path, src)
    (up / "docs" / "docs-graph.json").write_text("{}", encoding="utf-8")   # a later edit, not committed
    out, errors, _ = docjoin.pin(root, "upstream", up, "main", "docs/docs-graph.json")
    assert errors == [] and out == root / "docgraph" / "upstream.json"
    copy = json.loads(out.read_text(encoding="utf-8"))
    assert copy[docjoin.PINNED]["ref"] == sha and copy[docjoin.PINNED]["file"] == "docs/docs-graph.json"
    assert {k: v for k, v in copy.items() if k != docjoin.PINNED} == src     # the committed one, not the edit
    assert docgraph.validate(copy)[0] == []                                   # still a docgraph/v1 document
    assert _git(up, "status", "--porcelain") == "M docs/docs-graph.json"      # the clone as it was
    assert _git(up, "rev-parse", "HEAD") == sha


def test_pin_refuses_what_is_not_a_read_projects_valid_document_and_writes_nothing(tmp_path, monkeypatch, store):
    root = _registry(tmp_path, monkeypatch, store)
    bad = _doc([_n("item:1"), _n("item:1")])
    up, _ = _clone(tmp_path, bad)
    _, errors, _ = docjoin.pin(root, "demo", up, "main", "docs/docs-graph.json")
    assert "'demo' is not an access: read project" in errors[0]
    _, errors, _ = docjoin.pin(root, "upstream", up, "main", "docs/docs-graph.json")
    assert any("used twice" in e for e in errors)
    _, errors, _ = docjoin.pin(root, "upstream", up, "nope", "docs/docs-graph.json")
    assert "'nope' is not a commit of this clone" in errors[0]
    _, errors, _ = docjoin.pin(root, "upstream", up, "--upload-pack=x", "docs/docs-graph.json")
    assert "a commit or a tag" in errors[0]
    _, errors, _ = docjoin.pin(root, "upstream", up, "main", "docs/missing.json")
    assert "no docs/missing.json at" in errors[0]
    assert not (root / "docgraph").exists()


def test_brain_docgraph_pin_and_join(tmp_path, monkeypatch, store, capsys):
    root = _registry(tmp_path, monkeypatch, store)
    up, sha = _clone(tmp_path, _doc([_n("criterion:S1-1", phase="S1"), _n("milestone:S1")]))
    argv = ["--root", str(root), "docgraph"]
    assert cli.main([*argv, "pin", "upstream", "--from", str(up), "--ref", sha, "--file", "docs/docs-graph.json"]) == 0
    assert "pinned at " + sha[:12] in capsys.readouterr().out
    # the brain's own document: its item serves the read project's criterion, named by its joined id
    (root / "docgraph" / "mine.json").write_text(json.dumps(_doc(
        [_n("item:7", phase="S1")], [_e("item:7", "criterion:upstream/S1-1", "serves")])), encoding="utf-8")
    out = tmp_path / "joined.json"
    assert cli.main([*argv, "join", "--no-own", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert f"upstream (docgraph/upstream.json, pinned @ {sha[:12]})" in text and "mine (docgraph/mine.json, own)" in text
    joined = json.loads(out.read_text(encoding="utf-8"))
    assert docgraph.validate(joined)[0] == []
    assert not [f for f in joined["checks"] if f["id"] == "criterion.no-item"]   # served across the documents
    assert cli.main([*argv, "join", "--no-own", "--json"]) == 0
    assert [s["name"] for s in json.loads(capsys.readouterr().out)["sources"]] == ["mine", "upstream"]


def test_a_read_projects_copy_without_its_pin_and_a_bad_name_are_left_out(tmp_path, monkeypatch, store, capsys):
    root = _registry(tmp_path, monkeypatch, store)
    (root / "docgraph").mkdir()
    (root / "docgraph" / "upstream.json").write_text(json.dumps(_doc([_n("item:1")])), encoding="utf-8")
    (root / "docgraph" / "Bad Name.json").write_text(json.dumps(_doc([])), encoding="utf-8")
    (root / "docgraph" / "broken.json").write_text("{", encoding="utf-8")
    srcs = {s.name: s for s in docjoin.sources(root)}
    assert "whose document is a pinned copy" in srcs["upstream"].errors[0]
    assert "its name is its namespace" in srcs["Bad Name"].errors[0]
    assert "not a JSON document" in srcs["broken"].errors[0]
    lines = docjoin.check_lines(root)
    assert len(lines) == 3 and all(x.startswith("docgraph: ") for x in lines)
    assert cli.main(["--root", str(root), "docgraph", "join", "--no-own"]) == 1
    assert "left out" in capsys.readouterr().out


# --- joining ----------------------------------------------------------------------------------------------------------

def test_join_namespaces_ids_keeps_joined_ends_and_the_producers_findings():
    a = docjoin.Source("alpha", "docgraph/alpha.json", _doc(
        [_n("item:1", phase="S1"), _n("document:docs/a.md#x")],
        [_e("item:1", "item:2", "depends_on"), _e("item:1", "test:beta/9", "carries")],
        [{"id": "example.own-check", "severity": "info", "subjects": ["item:1"], "message": "m"}]))
    b = docjoin.Source("beta", "docgraph/beta.json", _doc([_n("test:9")]))
    bad = docjoin.Source("gamma", "docgraph/gamma.json", None, ["no"])
    j = docjoin.join([a, b, bad], "brain test")
    assert [n["id"] for n in j["nodes"]] == ["item:alpha/1", "document:alpha/docs/a.md#x", "test:beta/9"]
    assert j["nodes"][0]["phase"] == "alpha/S1" and j["nodes"][0]["project"] == "alpha"
    assert [(e["from"], e["to"]) for e in j["edges"]] == [("item:alpha/1", "item:alpha/2"),
                                                          ("item:alpha/1", "test:beta/9")]
    own = [f for f in j["checks"] if f["id"] == "example.own-check"]
    assert own == [{"id": "example.own-check", "severity": "info", "subjects": ["item:alpha/1"], "message": "m",
                    "by": "alpha"}]
    assert set(j["generated"]["sources"]) == {"alpha", "beta"}            # gamma is left out
    assert not [f for f in j["checks"] if f["id"] == "test.uncarried"]  # carried from the other document
    assert j["checks_run"] == list(docjoin.RUN)
    assert set(j["checks_run"]) | set(j["checks_not_run"]) == set(docgraph.CHECK_IDS)
    assert docgraph.validate(j)[0] == []


def test_a_finding_the_join_repeats_is_kept_once():
    a = docjoin.Source("alpha", "p", _doc([_n("criterion:c")], [], [
        {"id": "criterion.no-item", "severity": "error", "subjects": ["criterion:c"], "message": "producer's"}]))
    found = [f for f in docjoin.join([a], "t")["checks"] if f["id"] == "criterion.no-item"]
    assert len(found) == 1 and found[0]["by"] == "join"


# --- the checks -------------------------------------------------------------------------------------------------------

def _ids(doc):
    return sorted((f["id"], tuple(f["subjects"])) for f in docjoin.run_checks(doc))


def test_each_check_run_again_finds_its_case():
    doc = _doc([
        _n("milestone:S1"), _n("milestone:S2"),
        _n("criterion:c1", phase="S1"), _n("criterion:c2", phase="S1"),
        _n("item:1", phase="S1"), _n("item:2", phase="S1"), _n("item:3", phase="S2", status="closed"),
        _n("item:r", phase="S1", kind="review"),
        _n("test:t1"), _n("test:t2"), _n("threat:x"), _n("threat:y"),
        _n("decision:d", status="proposed"),
        _n("document:a", kind="how-to", updated="2026-01-01"), _n("document:g", kind="generated", updated="2026-01-01"),
        _n("item:5", updated="2026-02-01"),
    ], [
        _e("item:1", "criterion:c1", "serves"),
        _e("item:1", "test:t2", "carries"), _e("item:2", "test:t2", "carries"),
        _e("test:t2", "threat:x", "covers"),
        _e("item:1", "item:3", "depends_on"), _e("item:1", "item:404", "depends_on"),
        _e("item:r", "item:1", "depends_on"),
        _e("item:2", "decision:d", "decided_by"),
        _e("item:5", "document:a", "documented_in"), _e("item:5", "document:g", "documented_in"),
        _e("milestone:S1", "milestone:S2", "part_of"), _e("milestone:S2", "milestone:S1", "part_of"),
    ])
    assert _ids(doc) == sorted([
        ("criterion.no-item", ("criterion:c2",)),
        ("item.no-criterion", ("item:2",)),
        ("test.uncarried", ("test:t1",)),
        ("test.carried-twice", ("test:t2", "item:1", "item:2")),
        ("threat.untested", ("threat:y",)),
        ("depends.cross-phase", ("item:1", "item:3")),
        ("depends.cross-phase", ("item:1",)),
        ("phase.review-incomplete", ("item:r", "item:2")),
        ("cycle", ("milestone:S1", "milestone:S2")),
        ("proposed.cited-as-decided", ("item:2", "decision:d")),
        ("doc.stale", ("document:a", "item:5")),          # the generated one is exempt
    ])


def test_the_checks_hold_quietly_on_the_fixtures():
    """The contract's invented documents: the join runs over them without a crash, its findings well formed."""
    for which in ("older", "newer"):
        doc = json.loads((FIXTURES / f"{which}.json").read_text(encoding="utf-8"))
        for f in docjoin.run_checks(doc):
            assert f["id"] in docjoin.RUN and f["severity"] in docgraph.SEVERITIES and f["subjects"]
