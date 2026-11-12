"""docgraph/v1, the documentation graph's contract (wi-brain-docgraph-contract; docs/docgraph.md): the published
schema, the rules a schema cannot say, the evolution rule, the named checks and brain docgraph."""

import copy
import json
from pathlib import Path

import pytest

from brain import cli, docgraph, schema

FIXTURES = Path(__file__).parent / "fixtures" / "formats" / "docgraph" / "v1"
DOCS = Path(__file__).resolve().parents[1] / "docs" / "docgraph.md"


def fixture(which: str) -> dict:
    return json.loads((FIXTURES / f"{which}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("which", ["older", "newer"])
def test_both_sides_of_the_version_hold_to_the_contract(which):
    """A first producer's document and another's with keys of its own, a need and its own check: both valid, the
    unknown keys allowed at every level (read tolerantly, never refused, even in strict mode)."""
    doc = fixture(which)
    assert schema.validate("docgraph", doc, schema.STRICT) == ([], [])
    errors, notes = docgraph.validate(doc)
    assert errors == []
    if which == "newer":
        assert any("'item:wi-elsewhere' is not a node" in n for n in notes)
        assert any("'example.own-check' is the producer's own check" in n for n in notes)


def test_the_schema_is_registered_and_its_keywords_implemented():
    assert "docgraph" in schema.SCHEMAS and schema.unsupported(schema.load("docgraph")) == []
    assert schema.known_v("docgraph") == 1   # versioned by its id, not by a top-level v


def test_the_vocabularies_are_the_schemas():
    """The module's lists and the published schema say the same thing: a reader in another language reads the
    schema only."""
    s = schema.load("docgraph")
    assert tuple(s["$defs"]["node"]["properties"]["type"]["enum"]) == docgraph.NODE_TYPES
    assert tuple(s["$defs"]["node"]["properties"]["status"]["enum"]) == docgraph.STATUSES
    assert tuple(s["$defs"]["edge"]["properties"]["type"]["enum"]) == docgraph.EDGE_TYPES
    assert tuple(s["$defs"]["finding"]["properties"]["severity"]["enum"]) == docgraph.SEVERITIES


def test_the_named_checks_are_documented_one_for_one():
    """Every named check is in docs/docgraph.md's table with its severity, and the table names no other."""
    rows = [line.split("|") for line in DOCS.read_text(encoding="utf-8").splitlines() if line.startswith("| `")]
    documented = {r[1].strip().strip("`"): r[2].strip() for r in rows
                  if len(r) > 3 and r[2].strip() in docgraph.SEVERITIES}
    assert documented == {c.id: c.severity for c in docgraph.CHECKS}
    assert len(docgraph.CHECK_IDS) == len(set(docgraph.CHECK_IDS)) == 16


def _broken(mutate) -> list[str]:
    doc = copy.deepcopy(fixture("older"))
    mutate(doc)
    return docgraph.validate(doc)[0]


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d["nodes"].append(dict(d["nodes"][0])), "id 'decision:0005' used twice"),
    (lambda d: d["nodes"][0].update(id="item:0005"), "is not prefixed by its type 'decision'"),
    (lambda d: d["nodes"][0].update(source={"line": 3}), "nodes[0].source: names no path and no tracker"),
    (lambda d: d["nodes"][0].pop("source"), "nodes[0]: missing 'source'"),
    (lambda d: d["nodes"][0].update(type="wish"), "'wish' not in"),            # a new type is v2, not additive
    (lambda d: d["nodes"][0].update(status="active"), "'active' not in"),
    (lambda d: d["edges"][0].pop("source"), "edges[0]: missing 'source'"),     # a derived edge cites its source
    (lambda d: d["edges"][5].pop("reason"), "edges[5]: missing 'reason'"),     # a declared one gives its reason
    (lambda d: d["edges"][5].pop("confirmed"), "edges[5]: missing 'confirmed'"),
    (lambda d: d["edges"].append({"from": "decision:0005", "to": "need:N-1", "type": "constrains",
                                  "origin": "declared", "reason": "r", "confirmed": False}),
     "missing 'compatibility'"),
    (lambda d: d["nodes"].append({"id": "need:N-1", "type": "need", "title": "t", "source": {"path": "n.md"}}),
     "missing 'phase'"),
    (lambda d: d["checks_not_run"].append("cycle"), "check 'cycle' is both run and not run"),
    (lambda d: d["checks_not_run"].append("criterion.no-item") or d["checks_run"].remove("criterion.no-item"),
     "a finding of 'criterion.no-item', which the document says was not run"),
    (lambda d: d.pop("generated"), "missing 'generated'"),
    (lambda d: d["generated"].update(at="yesterday"), "is not a date-time"),
])
def test_what_breaks_the_contract_is_an_error(mutate, expected):
    errors = _broken(mutate)
    assert any(expected in e for e in errors), errors


def test_a_later_version_is_refused_and_judged_no_further():
    doc = fixture("newer")
    doc["schema"] = "docgraph/v2"
    doc["nodes"] = "anything"        # its keys may mean something else: not judged
    errors, notes = docgraph.validate(doc, where="g.json")
    assert errors == ["g.json: schema: docgraph/v2 is a later contract than this engine's docgraph/v1: brain update"]
    assert notes == []


def test_another_contract_is_an_error():
    doc = fixture("older")
    doc["schema"] = "brain.status/v1"
    assert any("must be 'docgraph/v1'" in e for e in docgraph.validate(doc)[0])


def test_a_malformed_document_is_reported_never_a_crash():
    """The schema reports the wrong types; the rules after it read past them (an unhashable check id, a subject list
    that is a string, a node that is not an object)."""
    doc = {"schema": "docgraph/v1", "generated": "now", "nodes": [3, {"id": "x"}], "edges": {"a": 1},
           "checks": [{"id": "cycle", "severity": "error", "subjects": "item:1"}, "x"],
           "checks_run": [{"id": "cycle"}], "checks_not_run": "cycle"}
    errors, _ = docgraph.validate(doc)
    assert errors and all(isinstance(e, str) for e in errors)
    assert docgraph.summary(doc)["by"] is None


def test_summary_counts():
    s = docgraph.summary(fixture("older"))
    assert s["nodes"]["decision"] == 3 and s["edges"]["contradicts"] == 1
    assert s["origins"] == {"declared": 1, "derived": 5} and s["findings"] == {"error": 1}
    assert (s["checks_run"], s["checks_not_run"]) == (4, 2)


# --- brain docgraph --------------------------------------------------------------------------------------------------

def test_validate_needs_no_brain_and_exits_on_an_invalid_document(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                 # no notes/graph anywhere above: no brain
    monkeypatch.delenv("BRAIN_ROOT", raising=False)
    bad = tmp_path / "bad.json"
    doc = fixture("older")
    doc["nodes"][0]["source"] = {}
    bad.write_text(json.dumps(doc), encoding="utf-8")
    notjson = tmp_path / "x.json"
    notjson.write_text("{", encoding="utf-8")
    assert cli.main(["docgraph", "validate", str(FIXTURES / "older.json"), str(FIXTURES / "newer.json")]) == 0
    out = capsys.readouterr().out
    assert "older.json: OK: 10 node(s), 6 edge(s), 1 finding(s) (1 error)" in out
    assert "note:" in out and "'item:wi-elsewhere'" in out
    assert cli.main(["docgraph", "validate", str(bad), str(notjson)]) == 1
    out = capsys.readouterr().out
    assert "bad.json: INVALID" in out and "names no path and no tracker" in out and "not a JSON document" in out


def test_validate_json_and_checks(capsys):
    assert cli.main(["docgraph", "validate", "--json", str(FIXTURES / "newer.json")]) == 0
    [r] = json.loads(capsys.readouterr().out)
    assert r["ok"] and r["errors"] == [] and r["summary"]["nodes"]["need"] == 1
    assert cli.main(["docgraph", "checks", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == list(docgraph.CHECK_IDS)
    assert set(rows[0]) == {"id", "subject", "severity", "means", "needs"}
    assert cli.main(["docgraph", "checks"]) == 0
    assert "doc.stale" in capsys.readouterr().out
