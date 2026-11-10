import json
from pathlib import Path

import pytest

from brain import audit, cli, features, graph

from conftest import git_init, run_git
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


# --- the matrix split by repo, and the public render (wi-brain-features-repo-split) ---

PUBLIC_CFG = {"v": 1, "identity": {"owner": "Ada"},
              "public": {"repos": ["acme/engine"], "deny": {"people": ["Ada"], "repos": ["ada-private"]}}}
OWNER_TITLE = "Owner-alone guard: refuses what only the owner does"


@pytest.fixture
def public_clone(tmp_path, monkeypatch):
    """Ada's config.json naming acme/engine public, and a checkout of the engine (repo sib) whose origin is it."""
    cfg = tmp_path / "ada-brain" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps(PUBLIC_CFG), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    clone = git_init(tmp_path / "engine")
    run_git(clone, "remote", "add", "origin", "https://github.com/acme/engine.git")
    return clone


def _seed_split(s):
    """lab's features, and the engine's (repo sib): one titled and named after its owner, its code, tests and docs
    in both repos, linked to lab's spec, ADR and item; a part of it in another domain."""
    _seed(s)
    for nid in ("test:sib:tests/test_guard.py", "test:lab:tests/test_hook.py", "doc:sib:README.md::guards",
                "doc:lab:docs/private.md::guard"):
        graph.add_item(s, nid, nid, node_type="WorkItem")   # any node: Test and Doc are the links layer's
    features.add(s, "feat-sib-ada-guard", "Ada-alone guard: refuses what only Ada does", "guards", "sib",
                 status="have", code=["code:sib:sib/guard.py", "code:lab:src/lab/hook.py"],
                 tests=["test:sib:tests/test_guard.py", "test:lab:tests/test_hook.py"],
                 docs=["doc:sib:README.md::guards", "doc:lab:docs/private.md::guard"], specs=["spec-x"],
                 adrs=["adr-2026-11-02-x"], items=["wi-x"])
    features.add(s, "feat-sib-ssh", "Over ssh too", "remote", "sib", status="partial", parent="feat-sib-ada-guard",
                 code=["code:sib:sib/ssh.py"])
    features.set_feature(s, "feat-sib-ada-guard", [f"public_title={OWNER_TITLE}", "public_id=feat-sib-owner-guard"])


def test_public_render_is_neutral_stable_and_loses_nothing_in_the_brain(fstore, public_clone):
    _seed_split(fstore)
    m = features.load_store(fstore)
    text = features.render(m, "sib", public=True)
    assert features.MARKER in text and "**2 features: 1 have, 1 partial, 0 planned, 0 no.**" in text
    assert f"**{OWNER_TITLE}** `feat-sib-owner-guard`" in text and "part of `feat-sib-owner-guard`" in text
    assert "[guard.py](sib/guard.py)" in text and "hook.py" not in text            # only the repo's own code
    assert "`test:sib:tests/test_guard.py`" in text and "test:lab" not in text
    assert "`doc:sib:README.md::guards`" in text and "doc:lab" not in text
    for private in ("Ada", "ada-guard", "spec-x", "adr-2026-11-02-x", "wi-x", "notes/graph", "feat-lab"):
        assert private not in text
    assert features.denied_lines(text) == []                                       # brain check --public passes it
    # deterministic: the same graph, nodes in any order, the same file
    nodes = [graph.load_yaml_list(f) for f in sorted((fstore / "nodes").glob("*.yaml"))]
    edges = [graph.load_yaml_list(f) for f in sorted((fstore / "edges").glob("*.yaml"))]
    shuffled = features.build([list(reversed(n)) for n in reversed(nodes)], edges)
    shuffled.coverage = m.coverage
    assert features.render(shuffled, "sib", public=True) == text == features.render(m, "sib", public=True)
    # the brain's own render keeps everything: the title, the id, the other repo's code and the records
    full = features.render(m, "sib")
    assert "**Ada-alone guard: refuses what only Ada does** `feat-sib-ada-guard`" in full
    assert "`lab:hook.py`" in full and "`spec-x`, `adr-2026-11-02-x`, `wi-x`" in full
    assert any("people term 'Ada'" in x for x in features.denied_lines(full))
    assert features.render(m, "lab", public=True).count("feat-sib") == 0         # each repo its own features
    assert "feat-sib" not in features.render(m, "lab")


def test_public_id_is_a_feature_id_no_other_node_has(fstore):
    _seed_split(fstore)
    for bad, why in (("public_id=Owner Guard", "is a feature id"), ("public_id=feat-lab-core", "already a node's id"),
                     ("public_id=feat-sib-owner-guard", "another feature's public_id")):
        with pytest.raises(features.FeatureError, match=why):
            features.set_feature(fstore, "feat-sib-ssh", [bad])
    assert features.set_feature(fstore, "feat-sib-ada-guard", ["public_id=feat-sib-owner-guard"])   # its own


def test_public_checkout_reads_the_remotes_against_public_repos(public_clone, tmp_path, monkeypatch):
    assert features.public_checkout(public_clone)
    other = git_init(tmp_path / "fork")
    run_git(other, "remote", "add", "origin", "https://github.com/acme/private-thing.git")
    assert not features.public_checkout(other)
    assert not features.public_checkout(tmp_path / "missing")
    run_git(other, "remote", "add", "upstream", "git@github.com:acme/engine.git")   # any remote of the list
    assert features.public_checkout(other)
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))                # no public.repos: never public
    assert not features.public_checkout(public_clone)


def test_cli_renders_the_public_matrix_into_the_engine_checkout(fstore, public_clone, tmp_path, monkeypatch,
                                                                  capsys):
    _seed_split(fstore)
    features.add(fstore, "feat-sib-notes", "Ada's notes", "notes", "sib")         # no public_title yet
    root = _cli_project(tmp_path, monkeypatch, fstore)
    out = public_clone / "FEATURES.md"
    base = ["--project", "lab", "--root", str(root), "features", "render", "--repo", "sib", "--out", str(out)]
    assert cli.main(base) == 1
    got = capsys.readouterr()
    assert "FEATURES.md of sib (public): missing" in got.out
    assert "warning: the public FEATURES.md of sib" in got.err and "people term 'Ada'" in got.err
    assert "public_title=" in got.err
    assert cli.main(base + ["--write"]) == 0 and "written (sib, public render)" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8") == features.render(features.load_store(fstore, "lab"), "sib",
                                                              "notes/graph", public=True)
    assert cli.main(base) == 0
    features.set_feature(fstore, "feat-sib-notes", ["public_title=The owner's notes"])
    assert cli.main(base) == 1                                                   # the neutral title: re-rendered
    capsys.readouterr()
    assert cli.main(base + ["--write"]) == 0 and capsys.readouterr().err == ""   # nothing denied left
    assert cli.main(["--project", "lab", "--root", str(root), "features", "render", "--write"]) == 0
    assert "feat-sib" not in (root / "FEATURES.md").read_text(encoding="utf-8")  # the brain's: its own features


def test_cli_check_accepts_the_full_render_in_a_public_clone_unless_strict(fstore, public_clone, tmp_path,
                                                                           monkeypatch, capsys):
    _seed_split(fstore)
    root = _cli_project(tmp_path, monkeypatch, fstore)
    out = public_clone / "FEATURES.md"
    out.write_text(features.render(features.load_store(fstore, "lab"), "sib", "notes/graph"), encoding="utf-8")
    base = ["--project", "lab", "--root", str(root), "features", "render", "--repo", "sib", "--out", str(out)]
    assert cli.main(base) == 0
    assert "(public): up to date (the full render: config.json features.public_strict" in capsys.readouterr().out
    conf = tmp_path / "ada-brain" / "config.json"
    conf.write_text(json.dumps({**PUBLIC_CFG, "features": {"public_strict": True}}), encoding="utf-8")
    assert features.public_strict()
    assert cli.main(base) == 1 and "(public): stale" in capsys.readouterr().out
    assert cli.main(base + ["--write"]) == 0 and cli.main(base) == 0              # the public render passes


def test_check_view_accepts_a_second_render_and_public_strict_is_off_by_default(tmp_path, monkeypatch):
    assert features.check_view("a\r\n", "b\n", "a\n") == "" and features.check_view("a\n", "b\n") == "not generated"
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
    assert not features.public_strict()
    for opts in ({}, {"public_strict": False}, {"public_strict": "yes"}, []):
        (tmp_path / "c.json").write_text(json.dumps({"v": 1, "features": opts}), encoding="utf-8")
        monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "c.json"))
        assert not features.public_strict()


def test_audit_compares_each_repo_with_its_own_render(fstore, public_clone):
    _seed_split(fstore)
    store = {f"notes/graph/{p.relative_to(fstore).as_posix()}": p.read_text(encoding="utf-8")
             for p in fstore.rglob("*.yaml")}
    m = features.load_store(fstore, "lab")
    lab = {**store, "README.md": README, "src/lab/__init__.py": "", "src/lab/core.py": "def run():\n    pass\n",
           "src/lab/cli.py": "def main():\n    pass\n", "FEATURES.md": features.render(m, "lab")}
    sib = {"README.md": README, "sib/__init__.py": "", "sib/guard.py": "def g():\n    pass\n",
           "sib/ssh.py": "def s():\n    pass\n"}
    root = Path("/m/lab")
    p = audit.projects.Project("demo", root, [root / "notes" / "graph"])
    cfgs = [audit.projects.Repo("lab", root), audit.projects.Repo("sib", public_clone)]
    from test_inventory import mem

    def measure(view, lab_view=lab["FEATURES.md"]):
        files = {**sib, **({"FEATURES.md": view} if view is not None else {})}
        return audit.measure(p, cfgs, {"lab": mem({**lab, "FEATURES.md": lab_view}, "lab"), "sib": mem(files, "sib")})

    def fix_of(res, repo):
        return next(f["fix"] for r in res["repos"] if r["name"] == repo for f in r["findings"]
                    if f["check"] == "features.md")

    public_view, full_view = features.render(m, "sib", public=True), features.render(m, "sib")
    assert ("features.md", "FEATURES.md") not in _found(measure(public_view), "sib")
    assert ("features.md", "FEATURES.md") not in _found(measure(None), "lab")     # lab's own: its render
    # the full render, what a public clone's file held before the public render: still passes by default
    assert ("features.md", "FEATURES.md") not in _found(measure(full_view), "sib")
    res = measure(public_view + "x")                                                 # neither render: stale
    assert _found(res, "sib")[("features.md", "FEATURES.md")] == "P0"
    assert "--repo sib --out <a worktree of sib>/FEATURES.md --write (the public render)" in fix_of(res, "sib")
    assert _found(measure(None), "sib")[("features.md", "FEATURES.md")] == "P2"     # missing, not production
    res = measure(public_view, lab_view=lab["FEATURES.md"] + "x")                    # the home repo's own fix
    assert fix_of(res, "lab") == "brain features render --write (run by brain sync), then commit it"


def test_audit_holds_a_public_clone_to_the_public_render_only_when_the_owner_opts_in(fstore, public_clone,
                                                                                     tmp_path, monkeypatch):
    _seed_split(fstore)
    store = {f"notes/graph/{p.relative_to(fstore).as_posix()}": p.read_text(encoding="utf-8")
             for p in fstore.rglob("*.yaml")}
    m = features.load_store(fstore, "lab")
    lab = {**store, "README.md": README, "src/lab/__init__.py": "", "FEATURES.md": features.render(m, "lab")}
    root = Path("/m/lab")
    p = audit.projects.Project("demo", root, [root / "notes" / "graph"])
    cfgs = [audit.projects.Repo("lab", root), audit.projects.Repo("sib", public_clone)]
    from test_inventory import mem

    def found(view, cfg):
        conf = tmp_path / "opt" / "config.json"
        conf.parent.mkdir(exist_ok=True)
        conf.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("BRAIN_CONFIG", str(conf))
        sib = {"README.md": README, "sib/__init__.py": "", "sib/guard.py": "def g():\n    pass\n", "FEATURES.md": view}
        res = audit.measure(p, cfgs, {"lab": mem(lab, "lab"), "sib": mem(sib, "sib")})   # a repo with code
        return [f for r in res["repos"] if r["name"] == "sib" for f in r["findings"] if f["check"] == "features.md"]

    public_view, full_view = features.render(m, "sib", public=True), features.render(m, "sib")
    strict = {**PUBLIC_CFG, "features": {"public_strict": True}}
    assert [f["severity"] for f in found(full_view, strict)] == ["P0"]              # the opt-in: public only
    assert "(the public render)" in found(full_view, strict)[0]["fix"]
    assert found(public_view, strict) == []
    # no public.repos: a sibling that is not a public clone is held to the full render, the plain fix
    plain = {"v": 1, "identity": {"owner": "Ada"}}
    assert found(full_view, plain) == []
    [stale] = found(public_view, plain)
    assert stale["severity"] == "P0" and "(the public render)" not in stale["fix"]
    assert stale["fix"] == ("from the brain's worktree, brain features render --repo sib --out <a worktree of sib>/"
                            "FEATURES.md --write, then commit it there")


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
