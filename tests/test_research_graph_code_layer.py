"""Code layer (spec 2026-10-17-graph-code-layer-design): CodeRef id grammar, the layer's rules in `graph check`,
the dev-local `code-check` against a fake sibling repo (read with ast, never imported), impact through
implemented_by, the `code` query, overlays carrying CodeRefs, the real store. Export: test_research_graph_export_gitnexus.py.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from research_graph.cli import main
from research_graph.code_layer import (
    CodeRef,
    check_code_refs,
    find_symbol,
    orphan_code_refs,
    parse_code_ref,
    structure_errors,
    symbol_span,
)
from research_graph.loader import apply_overlay, load_store
from research_graph.model import LayeredGraph
from tests.two_stores import two_stores

STORE = Path(__file__).parent / "fixtures" / "code_layer"

VENUE_PY = '''"""A fake venue adapter."""
from fake_pkg.store import save as reexported

RATE_CAP: float = 0.04
ALIASES, LIMITS = {}, {}
registry = {}
registry["x"] = 1

try:
    from fast import fast_path
except ImportError:
    def fast_path(x):
        return x

if True:
    def conditional():
        return 1


class FakeVenue:
    name = "fake"

    class Inner:
        pass

    def funding(self, symbol):
        def helper():
            return symbol
        return helper()


async def normalize(frame):
    return frame
'''


def _platform(root: Path) -> Path:
    """A fake platform root holding one sibling repo, ``fake-repo`` (``src/`` layout plus ``scripts/``)."""
    pkg = root / "fake-repo" / "src" / "fake_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "venue.py").write_text(VENUE_PY, encoding="utf-8")
    (pkg / "store.py").write_text("def save():\n    return None\n", encoding="utf-8")
    (pkg / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    (root / "fake-repo" / "scripts").mkdir()
    (root / "fake-repo" / "scripts" / "run.ps1").write_text("Write-Output hi\n", encoding="utf-8")
    return root


def _copy_store(tmp_path: Path) -> Path:
    dst = tmp_path / "store"
    shutil.copytree(STORE, dst)
    return dst


# -- id grammar ------------------------------------------------------------------------------------


def test_parse_code_ref_with_and_without_symbol():
    ref = parse_code_ref(
        "code:acme-data:acme_data/venues/lighter.py::LighterVenue.funding"
    )
    assert ref == CodeRef(
        "acme-data", "acme_data/venues/lighter.py", "LighterVenue.funding"
    )
    assert ref.repo_node == "repo-acme-data"
    assert parse_code_ref(ref.id) == ref
    whole = parse_code_ref("code:research-lab:scripts/monitoring_cycle.ps1")
    assert whole.symbol is None and whole.repo_node == "repo-research-lab"


@pytest.mark.parametrize(
    "bad, why",
    [
        ("acme-data:a.py", "must start with"),
        ("code:a.py", "expected code:"),
        ("code:repo:/abs/a.py", "bad path"),
        ("code:repo:../a.py", "bad path"),
        ("code:repo:pkg\\a.py", "bad path"),
        ("code:repo:pkg//a.py", "bad path"),
        ("code:repo:a.py::", "bad symbol"),
        ("code:repo:a.py::1x", "bad symbol"),
        ("code:repo:a.py::A..b", "bad symbol"),
        ("code:repo:config.yaml::key", "needs a .py file"),
    ],
)
def test_parse_code_ref_rejects(bad, why):
    with pytest.raises(ValueError, match=why):
        parse_code_ref(bad)


# -- symbol lookup (ast, no import) ----------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("FakeVenue", ("class", 20)),
        ("FakeVenue.funding", ("method", 26)),
        ("FakeVenue.Inner", ("class", 23)),
        ("FakeVenue.name", ("assign", 21)),
        ("normalize", ("function", 32)),
        ("RATE_CAP", ("assign", 4)),
        ("LIMITS", ("assign", 5)),
        ("fast_path", ("function", 12)),  # defined in the except block
        ("conditional", ("function", 16)),  # defined in an if block
    ],
)
def test_find_symbol_finds_definitions(symbol, expected):
    assert find_symbol(ast.parse(VENUE_PY), symbol) == expected


@pytest.mark.parametrize(
    "symbol",
    [
        "reexported",
        "registry.x",
        "FakeVenue.funding.helper",
        "normalize.frame",
        "FakeVenue.missing",
        "nope",
    ],
)
def test_find_symbol_ignores_imports_subscripts_and_function_bodies(symbol):
    # `registry` itself is defined; `registry.x` would need registry to be a class.
    assert find_symbol(ast.parse(VENUE_PY), symbol) is None


def test_symbol_span_covers_decorators_and_the_body():
    """The lines a change to the symbol touches (brain impact without GitNexus); find_symbol keeps the def line."""
    text = VENUE_PY + "\n\n@staticmethod\n@cache\ndef cached(x):\n    return x\n"
    tree = ast.parse(text)
    assert symbol_span(tree, "FakeVenue") == ("class", 20, 29)
    assert symbol_span(tree, "FakeVenue.funding") == ("method", 26, 29)
    assert symbol_span(tree, "ALIASES") == ("assign", 5, 5)
    assert symbol_span(tree, "cached") == ("function", 36, 39) and find_symbol(tree, "cached") == ("function", 38)
    assert symbol_span(tree, "FakeVenue.missing") is None


# -- graph check (CI-safe) -------------------------------------------------------------------------


def test_fixture_store_passes_the_structure_rules():
    g = load_store(STORE)
    assert g.nodes["code:fake-repo:fake_pkg/store.py"]["layer"] == "code"
    assert structure_errors(g) == [] and orphan_code_refs(g) == []


def test_structure_rules_reject_bad_wiring(tmp_path):
    store = _copy_store(tmp_path)
    (store / "nodes" / "bad.yaml").write_text(
        "- {id: 'code:nowhere:a.py', type: CodeRef, status: active, title: unknown repo}\n"
        "- {id: 'code:fake-repo:bad path.py::A..b', type: CodeRef, status: active, title: malformed}\n"
        "- {id: 'code:fake-repo:x.py', type: Dataset, status: active, title: reserved prefix}\n"
        "- {id: 'code:fake-repo:orphan.py', type: CodeRef, status: active, title: orphan}\n",
        encoding="utf-8",
    )
    (store / "edges" / "bad.yaml").write_text(
        "- {from: ad-x, to: tf-x, type: implemented_by}\n"
        "- {from: 'code:fake-repo:fake_pkg/store.py', to: ds-x, type: depends_on}\n"
        "- {from: edge-x, to: 'code:fake-repo:fake_pkg/venue.py::FakeVenue', type: depends_on}\n",
        encoding="utf-8",
    )
    g = load_store(store)
    errors = "\n".join(structure_errors(g))
    assert "code:nowhere:a.py: no Repo node 'repo-nowhere'" in errors
    assert "code:fake-repo:bad path.py::A..b: malformed CodeRef id: bad symbol" in errors
    assert "code:fake-repo:x.py: ids under 'code:' are reserved" in errors
    assert "ad-x->tf-x: implemented_by must point at a CodeRef" in errors
    assert "code:fake-repo:fake_pkg/store.py->ds-x: a CodeRef has no outgoing edge" in errors
    assert "only implemented_by may point at a CodeRef, got 'depends_on'" in errors
    orphans = orphan_code_refs(g)
    assert "code:fake-repo:orphan.py: CodeRef with no implemented_by" in orphans
    assert not any("venue.py" in o for o in orphans)


def test_cli_check_runs_the_code_rules(tmp_path, capsys):
    assert main(["--store", str(STORE), "--repo-root", str(tmp_path), "check"]) == 0
    store = _copy_store(tmp_path)
    (store / "nodes" / "orphan.yaml").write_text(
        "- {id: 'code:fake-repo:orphan.py', type: CodeRef, status: active, title: orphan}\n",
        encoding="utf-8",
    )
    assert main(["--store", str(store), "--repo-root", str(tmp_path), "check"]) == 0
    assert (
        "advisory: code:fake-repo:orphan.py: CodeRef with no implemented_by"
        in capsys.readouterr().out
    )
    (store / "edges" / "bad.yaml").write_text(
        "- {from: ad-x, to: tf-x, type: implemented_by}\n", encoding="utf-8"
    )
    assert main(["--store", str(store), "--repo-root", str(tmp_path), "check"]) == 1


# -- code-check (dev-local, reads the sibling checkouts) ------------------------------------------


def test_code_check_verdicts_against_a_fake_sibling_repo(tmp_path):
    findings = {f.id: f for f in check_code_refs(load_store(STORE), _platform(tmp_path))}
    verdict = {k: f.verdict for k, f in findings.items()}
    assert verdict == {
        "code:absent-repo:absent_pkg/mod.py::f": "SKIPPED",
        "code:fake-repo:fake_pkg/broken.py::oops": "UNPARSABLE",
        "code:fake-repo:fake_pkg/gone.py::Thing": "MISSING_FILE",
        "code:fake-repo:fake_pkg/store.py": "OK",
        "code:fake-repo:fake_pkg/venue.py::FakeVenue": "OK",
        "code:fake-repo:fake_pkg/venue.py::FakeVenue.funding": "OK",
        "code:fake-repo:fake_pkg/venue.py::RATE_CAP": "OK",
        "code:fake-repo:fake_pkg/venue.py::fast_path": "OK",
        "code:fake-repo:fake_pkg/venue.py::normalize": "OK",
        "code:fake-repo:fake_pkg/venue.py::renamed": "MISSING_SYMBOL",
        "code:fake-repo:scripts/run.ps1": "OK",
    }  # the retired CodeRef is not checked
    method = findings["code:fake-repo:fake_pkg/venue.py::FakeVenue.funding"]
    assert (method.file, method.kind, method.line) == ("src/fake_pkg/venue.py", "method", 26)
    script = findings["code:fake-repo:scripts/run.ps1"]
    assert (script.file, script.kind) == ("scripts/run.ps1", "file")  # outside src/: the repo root
    assert findings["code:fake-repo:fake_pkg/store.py"].kind == "module"


def test_code_check_matches_path_case_exactly(tmp_path):
    # Windows would open fake_pkg/Venue.py; Linux and GitNexus would not.
    store = _copy_store(tmp_path)
    (store / "nodes" / "case.yaml").write_text(
        "- {id: 'code:fake-repo:fake_pkg/Venue.py::FakeVenue', type: CodeRef, status: active, title: case}\n",
        encoding="utf-8",
    )
    findings = {
        f.id: f.verdict for f in check_code_refs(load_store(store), _platform(tmp_path / "p"))
    }
    assert findings["code:fake-repo:fake_pkg/Venue.py::FakeVenue"] == "MISSING_FILE"


def test_cli_code_check_exit_codes_and_json(tmp_path, capsys):
    root = _platform(tmp_path / "platform")
    out = tmp_path / "code_check.json"
    assert (
        main(
            ["--store", str(STORE), "code-check", "--platform-root", str(root), "--json", str(out)]
        )
        == 1
    )
    text = capsys.readouterr().out
    assert "MISSING_SYMBOL" in text and "fake-repo: not a git checkout" in text
    assert "absent-repo: not checked out" in text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["platform_root"] == str(root)
    row = next(f for f in report["findings"] if f["id"].endswith("::FakeVenue"))
    assert row == {
        "id": "code:fake-repo:fake_pkg/venue.py::FakeVenue",
        "verdict": "OK",
        "file": "src/fake_pkg/venue.py",
        "kind": "class",
        "line": 20,
        "detail": "",
    }

    # Only good refs left (and an absent repo, which is skipped, not failed): exit 0. The default platform
    # root is the parent of --repo-root.
    store = _copy_store(tmp_path)
    good = [
        "code:fake-repo:fake_pkg/venue.py::FakeVenue",
        "code:fake-repo:fake_pkg/store.py",
        "code:absent-repo:absent_pkg/mod.py::f",
    ]
    (store / "nodes" / "code.yaml").write_text(
        "".join(f"- {{id: '{c}', type: CodeRef, status: active, title: t}}\n" for c in good),
        encoding="utf-8",
    )
    (store / "edges" / "code.yaml").write_text(
        "".join(f"- {{from: ad-x, to: '{c}', type: implemented_by}}\n" for c in good),
        encoding="utf-8",
    )
    repo_root = root / "research-lab"
    repo_root.mkdir()
    assert main(["--store", str(store), "--repo-root", str(repo_root), "code-check"]) == 0
    assert "OK 2, SKIPPED 1" in capsys.readouterr().out


def test_cli_code_check_refuses_malformed_ids(tmp_path, capsys):
    store = _copy_store(tmp_path)
    (store / "nodes" / "bad.yaml").write_text(
        "- {id: 'code:fake-repo:../x.py', type: CodeRef, status: active, title: bad}\n",
        encoding="utf-8",
    )
    assert main(["--store", str(store), "code-check", "--platform-root", str(tmp_path)]) == 1
    assert "malformed CodeRef id" in capsys.readouterr().err


def test_overlay_code_refs_are_checked_too(tmp_path):
    # A sibling store (e.g. ops-repo ops/graph) links its own nodes to its own code with the same format.
    overlay = tmp_path / "fund" / "ops" / "graph"
    (overlay / "nodes").mkdir(parents=True)
    (overlay / "edges").mkdir()
    (overlay / "schema.yaml").write_text(
        "node_types: [Harness, CodeRef]\nedge_types: [implemented_by]\nstatuses: [active]\n"
        "layers: {operations: [Harness], code: [CodeRef]}\n",
        encoding="utf-8",
    )
    (overlay / "nodes" / "n.yaml").write_text(
        "- {id: harness-x, type: Harness, status: active, title: h}\n"
        "- {id: 'code:fake-repo:fake_pkg/store.py::save', type: CodeRef, status: active, title: s}\n"
        "- {id: 'code:fake-repo:fake_pkg/store.py::load', type: CodeRef, status: active, title: gone}\n",
        encoding="utf-8",
    )
    (overlay / "edges" / "e.yaml").write_text(
        "- {from: harness-x, to: 'code:fake-repo:fake_pkg/store.py::save', type: implemented_by}\n"
        "- {from: harness-x, to: 'code:fake-repo:fake_pkg/store.py::load', type: implemented_by}\n",
        encoding="utf-8",
    )
    (overlay / "external.yaml").write_text("", encoding="utf-8")
    g = apply_overlay(load_store(STORE), overlay, tmp_path)
    assert g.nodes["code:fake-repo:fake_pkg/store.py::save"]["layer"] == "code"
    assert structure_errors(g) == []
    findings = {f.id: f.verdict for f in check_code_refs(g, _platform(tmp_path / "platform"))}
    assert findings["code:fake-repo:fake_pkg/store.py::save"] == "OK"
    assert findings["code:fake-repo:fake_pkg/store.py::load"] == "MISSING_SYMBOL"


# -- impact and the `code` query -------------------------------------------------------------------


def test_impact_of_code_reaches_what_relies_on_it():
    lg = LayeredGraph(load_store(STORE))
    assert lg.impact("code:fake-repo:fake_pkg/venue.py::normalize") == {
        "data": ["ds-x", "tf-x"],
        "research": ["edge-x"],
    }
    assert lg.impact("code:fake-repo:fake_pkg/store.py") == {
        "data": ["ds-x"],
        "research": ["edge-x"],
    }


def test_code_query_direct_and_inherited():
    c = LayeredGraph(load_store(STORE)).code("edge-x")
    assert c["direct"] == ["code:fake-repo:fake_pkg/venue.py::normalize"]
    via = {e["id"]: e["via"] for e in c["inherited"]}
    assert via["code:fake-repo:fake_pkg/venue.py::FakeVenue"] == "ad-x"
    assert via["code:fake-repo:fake_pkg/store.py"] == "ds-x"
    assert via["code:fake-repo:fake_pkg/venue.py::RATE_CAP"] == "tf-x"
    assert "code:fake-repo:fake_pkg/venue.py::normalize" not in via  # already direct
    assert LayeredGraph(load_store(STORE)).code("repo-fake-repo") == {
        "node": "repo-fake-repo",
        "direct": [],
        "inherited": [],
    }


def test_cli_code_query(capsys):
    assert main(["--store", str(STORE), "code", "edge-x"]) == 0
    out = capsys.readouterr().out
    assert "direct: 1" in out and "code:fake-repo:fake_pkg/store.py  (via ds-x)" in out
    assert main(["--store", str(STORE), "code", "nope"]) == 1


def test_another_stores_coderef_an_edge_names_is_its_stores_to_check(tmp_path):
    """wi-brain-cross-store-edges: an implemented_by edge to another store's CodeRef passes the layer's rules (that
    store's own check reads its id and Repo node)."""
    home, _ = two_stores(tmp_path)
    schema = (home / "schema.yaml").read_text(encoding="utf-8").replace("decided_by]", "decided_by, implemented_by]")
    (home / "schema.yaml").write_text(schema, encoding="utf-8")
    (home / "edges" / "code.yaml").write_text("- {from: wi-a, to: 'code:elsewhere:x.py', type: implemented_by}\n",
                                              encoding="utf-8")
    foreign = {"wi-s": "parent", "ms-parent": "parent", "code:elsewhere:x.py": {"store": "lib", "type": "CodeRef"}}
    assert structure_errors(load_store(home, foreign=foreign)) == []
    foreign["code:elsewhere:x.py"] = {"store": "lib", "type": "Dataset"}
    assert structure_errors(load_store(home, foreign=foreign)) == [
        "wi-a->code:elsewhere:x.py: implemented_by must point at a CodeRef"]
