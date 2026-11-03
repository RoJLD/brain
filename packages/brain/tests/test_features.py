import json
from pathlib import Path

import pytest

from brain import audit, cli, features, graph

from test_audit import README, _found, _measure

SCHEMA = ("node_types: [WorkItem, Spec, ADR, Feature, CodeRef, Repo]\n"
          "edge_types: [decided_by, part_of, delivers, specified_by, implemented_by, tested_by, documented_in]\n"
          "statuses: [active, retired, todo, done, have, partial, planned, \"no\"]\n"
          "status_by_type:\n  Feature: [have, partial, planned, \"no\"]\n  CodeRef: [active, retired]\n"
          "  Repo: [active, retired]\n  WorkItem: [todo, done]\n")


@pytest.fixture
def fstore(tmp_path):
    """A store with the Feature and code layers, a spec, an ADR and an item."""
    s = tmp_path / "lab" / "notes" / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "edges").mkdir()
    (s / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (s / "nodes" / "work.yaml").write_text(
        "- {id: spec-x, type: Spec, status: active, title: \"Spec X\"}\n"
        "- {id: adr-2026-11-02-x, type: ADR, status: active, title: \"ADR X\"}\n"
        "- {id: wi-x, type: WorkItem, status: todo, title: \"Build X\"}\n", encoding="utf-8")
    return s


def _seed(s):
    features.add(s, "feat-lab-core", "Core: the engine | its CLI", "engine", "lab", status="have", value="high",
                 code=["src/lab/core.py::run", "src/lab/cli.py"], specs=["spec-x"], adrs=["adr-2026-11-02-x"])
    features.add(s, "feat-lab-core-fast", "Fast path", "engine", "lab", status="partial", parent="feat-lab-core",
                 code=["code:sib:sib/fast.py"])
    features.add(s, "feat-lab-search", "Search the matrix", "tools", "lab", items=["wi-x"])
    features.add(s, "feat-lab-never", "A thing we do not do", "tools", "lab", status="no", value="low")


def test_add_writes_nodes_coderefs_and_edges_once(fstore):
    _seed(fstore)
    nodes = (fstore / "nodes" / "features.yaml").read_text(encoding="utf-8")
    assert nodes.startswith("# Features:") and 'status: "no"' in nodes   # a bare no would read as false
    index = graph.node_index(fstore)
    assert index["feat-lab-never"][1]["status"] == "no"
    assert {i for i, (_, n) in index.items() if n["type"] in ("CodeRef", "Repo")} == {
        "repo-lab", "repo-sib", "code:lab:src/lab/core.py::run", "code:lab:src/lab/cli.py", "code:sib:sib/fast.py"}
    assert features.link(fstore, "feat-lab-core", code=["src/lab/cli.py"], specs=["spec-x"]) == []   # pairs exist
    new = features.link(fstore, "feat-lab-core", code=["src/lab/extra.py"])
    assert new == [{"from": "feat-lab-core", "to": "code:lab:src/lab/extra.py", "type": "implemented_by"}]
    m = features.load_store(fstore)
    assert m.code("feat-lab-core") == ["code:lab:src/lab/core.py::run", "code:lab:src/lab/cli.py",
                                       "code:lab:src/lab/extra.py"]
    assert m.parent("feat-lab-core-fast") == "feat-lab-core"
    assert m.into["feat-lab-search"] == [("delivers", "wi-x")]


@pytest.mark.parametrize("kwargs, message", [
    ({"fid": "lab-core"}, "a feature id is feat-"),
    ({"status": "done"}, "status 'done' is one of have"),
    ({"value": "huge"}, "value 'huge' is one of high"),
    ({"domain": ""}, "a domain is needed"),
    ({"code": ["src/x.py"], "specs": ["spec-nope"]}, "spec-nope: unknown node"),
    ({"parent": "spec-x"}, "a feature is part of a parent Feature"),
    ({"code": ["../x.py"]}, "bad path"),
    ({"code": ["code:spec:x.py"]}, "repo-spec: exists and is not a Repo"),
])
def test_add_refuses_bad_input_and_writes_nothing(fstore, kwargs, message):
    graph.add_item(fstore, "repo-spec", "not a repo", node_type="Spec", status="active")
    args = {"fid": "feat-lab-x", "title": "X", "domain": "d", "repo": "lab", **kwargs}
    with pytest.raises((features.FeatureError, ValueError), match=message):
        features.add(fstore, args.pop("fid"), args.pop("title"), args.pop("domain"), args.pop("repo"), **args)
    assert "feat-lab-x" not in graph.node_index(fstore)
    assert not (fstore / "nodes" / "code.yaml").exists() and not (fstore / "edges" / "features.yaml").exists()


def test_set_checks_before_writing(fstore):
    _seed(fstore)
    f = fstore / "nodes" / "features.yaml"
    before = f.read_text(encoding="utf-8")
    for bad in (["status=done"], ["value=huge"], ["domain="], ["type=WorkItem"]):
        with pytest.raises(features.FeatureError):
            features.set_feature(fstore, "feat-lab-search", bad)
    assert f.read_text(encoding="utf-8") == before
    with pytest.raises(features.FeatureError, match="unknown feature"):
        features.set_feature(fstore, "wi-x", ["status=have"])
    node = features.set_feature(fstore, "feat-lab-search", ["status=have", "module=D3"])
    assert node["status"] == "have" and node["props"]["module"] == "D3"


def test_render_groups_by_domain_nests_parts_and_is_stable(fstore):
    _seed(fstore)
    m = features.load_store(fstore)
    text = features.render(m, "lab")
    assert text == features.render(features.load_store(fstore), "lab")   # no date: the same graph, the same file
    assert features.MARKER in text and "**4 features: 1 have, 1 partial, 1 planned, 1 no.**" in text
    assert "| [engine](#engine) | 1 | 1 | 0 | 0 |" in text and "| [tools](#tools) | 0 | 0 | 1 | 1 |" in text
    engine = text.split("## engine")[1].split("## tools")[0]
    assert engine.index("`feat-lab-core`") < engine.index("↳ **Fast path** `feat-lab-core-fast`")
    assert "Core: the engine \\| its CLI" in engine                       # a pipe cannot break the table
    assert "[core.py::run](src/lab/core.py), [cli.py](src/lab/cli.py)" in engine
    assert "`sib:fast.py`" in engine                                      # another repo's code: not a link
    assert "`spec-x`, `adr-2026-11-02-x`" in engine
    assert "`wi-x`" in text.split("## tools")[1]
    assert "| Module |" not in text and "| Tests |" not in text and "| Docs |" not in text
    features.set_feature(fstore, "feat-lab-core", ["module=D3"])
    graph.add_item(fstore, "test-core", "tests/test_core.py", node_type="WorkItem")   # any node: Test arrives later
    features.link(fstore, "feat-lab-core", tests=["test-core"])
    text = features.render(features.load_store(fstore), "lab")
    assert "| Feature | Status | Value | Module | Code | Tests | Links |" in text and "| D3 |" in text
    assert features.render(m, "other").endswith("No feature yet.\n")
    assert features.check_view(None, text) == "missing"
    assert features.check_view(text.replace("\n", "\r\n"), text) == ""     # a CRLF checkout is the same file
    assert features.check_view(text + "x", text) == "stale"
    assert features.check_view("# my features\n", text) == "not generated"


def test_index_list_search_show_and_rebuild(fstore):
    _seed(fstore)
    db = features.open_index(fstore, "lab")
    try:
        assert [f["id"] for f in features.query_list(db)] == ["feat-lab-core", "feat-lab-core-fast",
                                                              "feat-lab-never", "feat-lab-search"]
        assert [f["id"] for f in features.query_list(db, status="have")] == ["feat-lab-core"]
        assert [f["id"] for f in features.query_list(db, domain="tools", value="low")] == ["feat-lab-never"]
        assert [f["id"] for f in features.query_search(db, "matr")] == ["feat-lab-search"]   # a prefix
        assert features.query_search(db, "feat-lab-core-fast")[0]["id"] == "feat-lab-core-fast"   # then its parent
        assert {f["id"] for f in features.query_search(db, "spec x")} == {"feat-lab-core"}  # a link's title
        assert features.query_search(db, "core.py run")[0]["id"] == "feat-lab-core"         # its code
        assert features.query_search(db, '"; DROP') == []
        assert features.query_search(db, "  ") == []
        show = features.query_show(db, "feat-lab-core")
        assert show["props"]["domain"] == "engine"
        assert {(x["dir"], x["type"], x["other"]) for x in show["links"]} >= {
            ("out", "implemented_by", "code:lab:src/lab/cli.py"), ("out", "specified_by", "spec-x"),
            ("in", "part_of", "feat-lab-core-fast")}
        assert features.query_show(db, "feat-nope") is None
        db.execute("UPDATE meta SET value = '0' WHERE key = 'fts'")   # an SQLite without FTS5: LIKE
        assert [f["id"] for f in features.query_search(db, "matrix search")] == ["feat-lab-search"]
    finally:
        db.close()
    path = features.index_path(fstore, "lab")
    assert path.is_file() and path.parent.parent == features.paths.brain_home()
    features.add(fstore, "feat-lab-new", "Brand new", "tools", "lab")
    db = features.open_index(fstore, "lab")   # the store changed: rebuilt
    try:
        assert "feat-lab-new" in {f["id"] for f in features.query_list(db)}
    finally:
        db.close()


def test_named_statuses_in_pr_text():
    text = ("Delivers feat-brain-x: have and feat-brain-y -> partial; feat-brain-z=no, feat-brain-w → planned.\n"
            "Mentions feat-brain-bare and xfeat-brain-q: have, feat-brain-r: done.")
    assert features.named(text) == [("feat-brain-x", "have"), ("feat-brain-y", "partial"), ("feat-brain-z", "no"),
                                    ("feat-brain-w", "planned")]


def test_sync_prs_in_merge_order_once_and_a_later_hand_change_stands(fstore, capsys):
    _seed(fstore)
    prs = [{"number": 7, "title": "Search", "body": "feat-lab-search: partial", "mergedAt": "2026-11-01T10:00:00Z"},
           {"number": 9, "title": "Search done", "body": "feat-lab-search: have\nfeat-lab-ghost: have",
            "mergedAt": "2026-11-02T10:00:00Z"},
           {"number": 8, "title": "Core", "body": "keeps feat-lab-core: have", "mergedAt": "2026-11-01T12:00:00Z"}]
    assert features.sync_prs(fstore, [("lab", fstore)], fetch=lambda _: prs) == 2
    out = capsys.readouterr().out
    assert "feat-lab-search planned -> have (lab #9)" in out and "feat-lab-core have, evidence lab #8" in out
    assert "lab #9 names feat-lab-ghost, which is not a feature" in out
    node = graph.node_index(fstore)["feat-lab-search"][1]
    assert node["status"] == "have" and node["props"]["status_pr"] == "lab #9"
    assert node["props"]["status_merged"] == "2026-11-02T10:00:00Z"
    assert features.sync_prs(fstore, [("lab", fstore)], fetch=lambda _: prs) == 0   # applied once
    features.set_feature(fstore, "feat-lab-search", ["status=partial"])               # by hand, later
    assert features.sync_prs(fstore, [("lab", fstore)], fetch=lambda _: prs) == 0
    assert graph.node_index(fstore)["feat-lab-search"][1]["status"] == "partial"
    assert features.sync_prs(fstore, [("lab", fstore)], fetch=lambda _: None) == 0
    assert "the merged PRs of lab were not read (gh)" in capsys.readouterr().out


def _cli_project(tmp_path, monkeypatch, fstore):
    root = fstore.parent.parent
    (tmp_path / "projects.yaml").write_text(f"lab:\n  root: {root.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    return root


def test_cli_add_render_check_list_and_sync_offline(fstore, tmp_path, monkeypatch, capsys):
    root = _cli_project(tmp_path, monkeypatch, fstore)
    base = ["--project", "lab", "--root", str(root), "features"]
    assert cli.main(base + ["add", "feat-lab-core", "--title", "Core", "--domain", "engine", "--status", "have",
                            "--code", "src/lab/core.py"]) == 0
    assert "add: feat-lab-core [have]" in capsys.readouterr().out
    assert graph.node_index(fstore)["feat-lab-core"][1]["props"]["repo"] == "lab"   # the root's repo by default
    assert cli.main(base + ["add", "feat-lab-bad", "--title", "B", "--domain", "d", "--spec", "spec-nope"]) == 1
    assert "spec-nope: unknown node" in capsys.readouterr().err
    assert cli.main(base + ["link", "feat-lab-core", "--spec", "spec-x"]) == 0
    assert cli.main(base + ["set", "feat-lab-core", "value=high"]) == 0
    capsys.readouterr()
    assert cli.main(base + ["render"]) == 1
    assert "FEATURES.md of lab: missing" in capsys.readouterr().out
    assert cli.main(base + ["render", "--write"]) == 0 and (root / "FEATURES.md").is_file()
    assert cli.main(base + ["render"]) == 0
    assert cli.main(base + ["render", "--repo", "sib"]) == 1   # another repo: --out its worktree
    assert cli.main(base + ["list", "--json"]) == 0
    capsys.readouterr()
    assert cli.main(base + ["search", "core"]) == 0 and "feat-lab-core" in capsys.readouterr().out
    assert cli.main(base + ["search", "zzz"]) == 0 and "no feature matches" in capsys.readouterr().out
    assert cli.main(base + ["show", "feat-lab-core", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "high"
    assert cli.main(base + ["show", "feat-lab-nope"]) == 1
    (root / "FEATURES.md").write_text("# by hand\n", encoding="utf-8")
    assert cli.main(base + ["render", "--write"]) == 1           # not generated: never overwritten
    assert "is not generated" in capsys.readouterr().err
    (root / "FEATURES.md").unlink()
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda r, s, *a: calls.append(a) or 0)
    monkeypatch.setattr(features, "fetch_prs", lambda _: pytest.fail("--offline calls gh"))
    assert cli.main(["--project", "lab", "--root", str(root), "sync", "--offline"]) == 0
    assert calls == [("sync", "--write"), ("kanban", "--write")] and (root / "FEATURES.md").is_file()


def test_audit_features_md_and_links(fstore):
    _seed(fstore)
    features.add(fstore, "feat-lab-claimed", "Claimed, no code", "tools", "lab", status="have")
    store = {f"notes/graph/{p.relative_to(fstore).as_posix()}": p.read_text(encoding="utf-8")
             for p in fstore.rglob("*.yaml")}
    code = {"README.md": README, "src/lab/__init__.py": "", "src/lab/core.py": "def run():\n    pass\n",
            "src/lab/cli.py": "def main():\n    pass\n", "src/lab/orphan.py": "def f():\n    pass\n",
            "tests/test_core.py": "x\n", "tests/test_cli.py": "x\n", "tests/test_orphan.py": "x\n"}
    res = _measure({"lab": {**store, **code}}, {"lab": {"production": True}})
    found = _found(res)
    assert found[("features.md", "FEATURES.md")] == "P1"                    # missing, on a production repo
    assert found[("feature.links", "src/lab/orphan.py")] == "P1"            # no feature is implemented by it
    assert ("feature.links", "src/lab/core.py") not in found                # a symbol's CodeRef covers its file
    assert found[("feature.links", "feat-lab-claimed")] == "P1"             # have, and no implemented_by
    assert ("feature.links", "feat-lab-core-fast") not in found            # partial, its code in another repo
    assert ("feature.links", "feat-lab-search") not in found               # planned: no code needed
    assert _found(_measure({"lab": {**store, **code}}))[("feature.links", "src/lab/orphan.py")] == "P2"   # not prod
    m = features.load_store(fstore, "lab")
    view = features.render(m, "lab")
    res = _measure({"lab": {**store, **code, "FEATURES.md": view}})
    assert ("features.md", "FEATURES.md") not in _found(res)
    res = _measure({"lab": {**store, **code, "FEATURES.md": view.replace("partial", "have", 1)}})
    assert _found(res)[("features.md", "FEATURES.md")] == "P0"              # stale: states something false
    assert "features.md" not in [x["check"] for x in res["repos"][0]["not_measured"]]


def test_audit_without_the_feature_type_pending_per_repo_unless_featured_today():
    plain = {"notes/graph/schema.yaml": "node_types: [WorkItem]\n", "README.md": README, "src/lab/__init__.py": "",
             "src/lab/core.py": "def run():\n    pass\n", "tests/test_core.py": "x\n"}
    res = _measure({"lab": plain})
    lab = res["repos"][0]
    assert {"check": "features.md", "owner": audit.NO_FEATURES} in lab["not_measured"]
    assert not any(c.startswith("feature") for c, _ in _found(res))
    assert audit.milestone([{**res, "counts": {"P0": 0, "P1": 0, "P2": 0}}], {"weeks": [{}], "falling": 4})[
        "pending"] >= ["feature.links", "features.md"]
    root = Path("/m/lab")   # a past week of a project that has the type today: measured, nothing linked yet
    p = audit.projects.Project("demo", root, [root / "notes" / "graph"])
    from test_inventory import mem
    res = audit.measure(p, [audit.projects.Repo("lab", root)], {"lab": mem(plain, "lab")}, featured=True)
    assert {u for c, u in _found(res) if c.startswith("feature")} == {"FEATURES.md", "src/lab/core.py"}
