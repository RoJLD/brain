import json
from pathlib import Path

import pytest

from brain import audit, cli, graph, links, projects

from conftest import run_git
from test_inventory import mem

SCHEMA = ("node_types: [WorkItem, Spec, Plugin, Skill, Hook, CodeRef, Doc, Test, Workflow]\n"
          "edge_types: [specified_by, part_of, documented_in, tested_by, runs]\n"
          "statuses: [active, todo]\n")
HOOKS = {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/start.sh" x'}]},
                                    {"hooks": [{"type": "command",
                                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/other.sh"'}]}]}}
NODES = """\
- {id: wi-a, type: WorkItem, status: todo, title: "A"}
- {id: wi-b, type: WorkItem, status: todo, title: "B"}
- {id: spec-s, type: Spec, status: active, title: "S", anchor: "docs/specs/s.md#s"}
- {id: plugin-core, type: Plugin, status: active, title: "core", anchor: "plugins/core/.claude-plugin/plugin.json#core"}
- {id: skill-close, type: Skill, status: active, title: "close", anchor: "plugins/core/skills/close/SKILL.md#close"}
- {id: hook-start, type: Hook, status: active, title: "start: says hello (start.sh)",
   anchor: "plugins/core/hooks/hooks.json#sessionstart"}
- {id: "code:demo:p/a.py", type: CodeRef, status: active, title: "a"}
- {id: "code:demo:p/b.py::B", type: CodeRef, status: active, title: "B"}
"""


def _tree():
    return mem({
        "notes/graph/schema.yaml": SCHEMA, "notes/graph/nodes/work.yaml": NODES,
        "notes/graph/nodes/_generated_links.yaml": "- {id: doc:old, type: Doc, status: active}\n",   # never read
        "notes/graph/edges/work.yaml": '- {from: wi-a, to: "code:demo:p/a.py", type: implemented_by}\n'
                                       '- {from: wi-b, to: "code:demo:p/b.py::B", type: implemented_by}\n',
        "README.md": "# demo\n\nIntro for `wi-a`.\n\n## Install\n\nRun hooks/start.sh, see src/p/a.py.\n\n"
                     "```\n## not a heading\n```\n\n## Plugin\n\nplugins/core/ and plugins/core/skills/close/SKILL.md."
                     "\n\n## Install\n\nAgain (wi-b).\n",
        "docs/guide.md": "Nothing the graph knows.\n",
        "docs/specs/s.md": "# S\n\n## 3. Themes\n\n### 3.7 Links — P1\n\nItems: `wi-b`, spec-s.\n\n#### deep\n\nx\n",
        "docs/specs/t.md": "# T\n\nwi-a.\n",
        "plugins/core/.claude-plugin/plugin.json": "{}", "plugins/core/README.md": "# core\n\nThe plugin.\n",
        "plugins/core/skills/close/SKILL.md": "# close\n", "plugins/core/hooks/hooks.json": json.dumps(HOOKS),
        "plugins/core/hooks/start.sh": "echo hi\n", "plugins/core/hooks/other.sh": "echo\n",
        "pyproject.toml": '[tool.setuptools.packages.find]\nwhere = ["src"]\n'
                          '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        "src/p/__init__.py": "", "src/p/a.py": "def f():\n    pass\n", "src/p/b.py": "class B:\n    pass\n",
        "tests/test_a.py": '"""Tests of p.a."""\nfrom p.a import f\n\n\ndef test_f():\n    f()\n\n\n'
                           "class TestMore:\n    def test_x(self):\n        pass\n\n    def helper(self):\n"
                           "        pass\n\n\nclass TestSkip:\n    def __init__(self):\n        pass\n\n"
                           "    def test_no(self):\n        pass\n",
        "tests/unit/test_hook.py": 'import subprocess\n\n\ndef test_start():\n    subprocess.run(["bash", "start.sh"])\n',
        "tests/unit/x.Tests.ps1": "Describe 'x' {\n  It 'one' {}\n  It \"two\" {}\n}\n",
        ".github/workflows/ci.yml": "name: CI\non: [push, pull_request]\njobs:\n"
                                    "  unit:\n    runs-on: ubuntu-latest\n    steps:\n"
                                    "      - run: pip install pytest pyyaml\n"
                                    "      - run: python -m pytest tests/unit/test_hook.py::test_start -q\n"
                                    "  all:\n    name: Everything\n    steps:\n      - run: |\n          pip install .\n"
                                    "          pytest -q\n"
                                    "  pester:\n    steps:\n      - run: Invoke-Pester -CI\n"
                                    "  deploy:\n    steps:\n      - run: ./deploy.sh\n",
    }, "demo")


def test_sections_cut_at_headings_with_github_anchors_and_short_keys():
    secs = links.sections("README.md", "pre\n# Top\n\n## A b: c\n\n```\n# fenced\n```\n### deep\n## A b: c\n")
    assert [(s.title, s.slug, s.key) for s in secs] == [("Top", "top", "top"), ("A b: c", "a-b-c", "a-b-c"),
                                                        ("A b: c", "a-b-c-1", "a-b-c-2")]
    assert secs[0].text.startswith("pre\n") and "### deep" in secs[1].text   # level 3 stays in a README section
    spec = links.sections("docs/specs/s.md", "# S\n## 3. Thèmes\n### 3.7 Graphe — P1 (tests : P2)\n")
    assert [(s.slug, s.key) for s in spec] == [("s", "s"), ("3-thèmes", "3"),
                                               ("37-graphe--p1-tests--p2", "3.7")]
    assert [(s.title, s.key) for s in links.sections("docs/x.md", "no heading\n")] == [("docs/x.md", "")]
    # research_graph checks a fragment that starts with a date against '## <date>' headings: GitHub's id form
    dated = links.sections("docs/n.md", "# 2026-11-02 — Notes\n")[0]
    assert links.anchor("docs/n.md", dated) == "docs/n.md#user-content-2026-11-02--notes"
    assert links.anchor("docs/x.md", links.sections("docs/x.md", "x\n")[0]) == "docs/x.md#top"
    assert links.short_key("Évaluer [la file](x.md) avant tout, puis le reste du travail prévu") == \
        "evaluer-la-file-avant-tout-puis-le-reste"


def test_derive_docs_tests_and_workflows():
    lk = links.derive(_tree(), "demo")
    by = {n["id"]: n for n in lk.nodes}
    edges = {(e["from"], e["to"]): e["type"] for e in lk.edges}
    doc = "doc:demo:README.md::"
    assert [i for i in lk.docs["README.md"]] == [doc + "demo", doc + "install", doc + "plugin", doc + "install-2"]
    assert by[doc + "install-2"]["anchor"] == "README.md#install-1" and "doc:old" not in by
    assert by[doc + "install"]["props"]["paths"] == ["plugins/core/hooks/start.sh", "src/p/a.py"]
    documented = {(s, d) for (s, d), t in edges.items() if t == "documented_in"}
    assert {("wi-a", doc + "demo"), ("wi-b", doc + "install-2"), ("hook-start", doc + "install"),
            ("wi-a", doc + "install"),   # src/p/a.py, the file of the CodeRef wi-a is implemented_by
            ("plugin-core", doc + "plugin"), ("skill-close", doc + "plugin"),
            ("plugin-core", "doc:demo:plugins/core/README.md::core"),   # a doc inside the plugin's folder
            ("wi-b", "doc:demo:docs/specs/s.md::3.7"), ("wi-a", "doc:demo:docs/specs/t.md::t")} <= documented
    assert not {d for s, d in documented if d.startswith("doc:demo:docs/guide.md")}
    assert ("spec-s", "doc:demo:docs/specs/s.md::3.7") not in edges   # a spec's own sections, part_of instead
    assert edges[("doc:demo:docs/specs/s.md::3.7", "spec-s")] == "part_of"
    assert lk.docs["docs/specs/s.md"] == ["doc:demo:docs/specs/s.md::s", "doc:demo:docs/specs/s.md::3",
                                          "doc:demo:docs/specs/s.md::3.7"]   # #### stays in 3.7
    assert lk.specs == {"docs/specs/s.md": "spec-s", "docs/specs/t.md": ""}
    # tests: a static collection, folders, covers, tested_by from a CodeRef and a Hook
    t = "test:demo:tests/"
    assert by[t + "test_a.py"]["title"] == "tests/test_a.py: Tests of p.a."
    assert by[t + "test_a.py"]["props"] == {"framework": "pytest", "cases": 2, "covers": ["src/p/a.py"]}
    assert by[t + "unit/x.Tests.ps1"]["props"] == {"framework": "pester", "cases": 2}
    assert by["test:demo:tests"]["props"] == {"modules": 3, "cases": 5}
    assert edges[(t + "unit/test_hook.py", "test:demo:tests/unit")] == "part_of"
    assert edges[("test:demo:tests/unit", "test:demo:tests")] == "part_of"
    assert edges[("wi-a", t + "test_a.py")] == "tested_by"   # through its CodeRef
    assert edges[("hook-start", t + "unit/test_hook.py")] == "tested_by"
    assert not [(s, d) for s, d in edges if s.startswith("code:") or d.startswith("code:")]   # research_graph's rule
    assert not [d for s, d in edges if s == "wi-b" and d.startswith("test:")]   # no test covers p/b.py
    assert lk.tested == {t + "test_a.py", t + "unit/test_hook.py"}
    # workflows: one node per job; runs from pytest and Invoke-Pester steps, never from pip install pytest
    w = "workflow:demo:.github/workflows/ci.yml::"
    assert by[w + "unit"]["props"] == {"triggers": "push, pull_request", "runs_on": "ubuntu-latest"}
    assert by[w + "all"]["title"] == "CI: Everything" and by[w + "all"]["anchor"] == ".github/workflows/ci.yml#all"
    runs = {(s, d) for (s, d), ty in edges.items() if ty == "runs"}
    assert runs == {(w + "unit", t + "unit/test_hook.py"), (w + "all", "test:demo:tests"),
                    (w + "pester", t + "unit/x.Tests.ps1")}


def test_hook_scripts_named_by_the_title_or_the_id():
    t = _tree()
    node = {"id": "hook-other", "type": "Hook", "title": "no script named",
            "anchor": "plugins/core/hooks/hooks.json#sessionstart"}
    assert links.hook_scripts(t, node) == {"plugins/core/hooks/other.sh"}
    assert links.hook_scripts(t, {**node, "id": "hook-x"}) == set()   # two scripts in the event, none named
    assert links.hook_scripts(t, {**node, "anchor": "plugins/core/hooks/hooks.json#stop"}) == set()


def _measure(files: dict, name: str = "demo"):
    root = Path("/m") / name
    p = projects.Project("demo", root, [root / "notes" / "graph"])
    return audit.measure(p, [projects.Repo(name, root)], {name: mem(files, name)})


def test_a_generated_doc_is_held_to_neither_doc_links_nor_doc_dead_ref():
    """The technical reference's pages (wi-brain-reference-scout): a module page with nothing to name, a quoted title
    that names a path of another repo. Nothing in them is fixed by hand: the scout refused the reference's first
    commit for them (doc.links on its empty module pages, doc.dead-ref on quoted paths)."""
    page = ("# K3 a module\n\nGENERATED by `brain reference` from `notes/graph`. Do not edit.\n\n## Items\n\n"
            "None. A quoted title: notes/roadmap.md, scripts/gone.ps1.\n")
    res = _measure({"notes/graph/schema.yaml": SCHEMA, "notes/graph/nodes/work.yaml": NODES,
                    "scripts/run.ps1": "x\n", "docs/reference/modules/K3.md": page,
                    "docs/hand.md": "# Hand\n\nNothing the graph knows; scripts/gone.ps1.\n"})
    found = {(f["check"], f["unit"]) for f in res["repos"][0]["findings"]}
    assert ("doc.links", "docs/hand.md") in found and ("doc.dead-ref", "docs/hand.md#scripts/gone.ps1") in found
    assert not {u for c, u in found if c in ("doc.links", "doc.dead-ref") and u.startswith("docs/reference/")}


def test_audit_measures_doc_and_test_links_where_the_store_takes_them():
    res = audit.measure(projects.Project("demo", Path("/m/demo"), [Path("/m/demo/notes/graph")]),
                        [projects.Repo("demo", Path("/m/demo"))], {"demo": _tree()})
    r = res["repos"][0]
    got = {(f["check"], f["unit"]): f["severity"] for f in r["findings"] if f["check"] in ("doc.links", "test.links")}
    assert got == {("doc.links", "docs/guide.md"): "P2", ("doc.links", "docs/specs/t.md"): "P2",
                   ("test.links", "tests/unit/x.Tests.ps1"): "P2"}
    assert {x["check"] for x in r["not_measured"]} & {"doc.links", "test.links"} == set()
    assert res["linked"] == {"demo": ("notes/graph", ["Doc", "Test", "Workflow"], "demo")}
    # a store without the types, and a repo with no store: still listed as not measured, with the reason
    bare = _measure({"README.md": "# x\n" + "line\n" * 12, "notes/graph/schema.yaml": "node_types: [WorkItem]\n",
                     "src/q.py": "def f():\n    pass\n"})
    owners = {x["check"]: x["owner"] for x in bare["repos"][0]["not_measured"]}
    assert owners["doc.links"] == "notes/graph has no Doc type" and owners["test.links"] == "notes/graph has no Test type"
    none = _measure({"README.md": "# x\n" + "line\n" * 12})
    assert {x["check"]: x["owner"] for x in none["repos"][0]["not_measured"]}["doc.links"] == \
        "no store of its own to hold the links, and no CodeRef of the project's store names it"
    assert audit.CHECKS["test.links"].scout == "never" and audit.RULESET >= 2   # 2 brought doc.links and test.links


def test_sync_writes_the_links_and_check_warns_when_stale(tmp_path, monkeypatch, make_repo, capsys, request):
    repo = make_repo("demo", {"notes/graph/schema.yaml": SCHEMA, "notes/graph/nodes/work.yaml": NODES,
                              "notes/graph/edges.yaml": "[]\n", "README.md": "# demo\n\nAbout wi-a.\n",
                              "tests/test_x.py": "def test_x():\n    pass\n"})
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {repo.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph", lambda root, store, *a: 0)
    assert cli.main(["--project", "demo", "sync"]) == 0
    assert "links graph: 3 node(s), 2 edge(s)" in capsys.readouterr().out
    nodes = graph.load_yaml_list(repo / "notes" / "graph" / "nodes" / links.GENERATED)
    assert [n["id"] for n in nodes] == ["doc:demo:README.md::demo", "test:demo:tests", "test:demo:tests/test_x.py"]
    assert graph.load_yaml_list(repo / "notes" / "graph" / "edges" / links.GENERATED) == [
        {"from": "test:demo:tests/test_x.py", "to": "test:demo:tests", "type": "part_of"},
        {"from": "wi-a", "to": "doc:demo:README.md::demo", "type": "documented_in"}]
    assert cli.main(["--project", "demo", "check"]) == 0
    assert "stale" not in capsys.readouterr().out
    (repo / "README.md").write_text("# demo\n\n## New\n\nwi-b.\n", encoding="utf-8")
    assert cli.main(["--project", "demo", "check"]) == 0   # on main, no views.strict: the warnings as before
    out = capsys.readouterr().out
    assert "warning: nodes/_generated_links.yaml is stale: brain sync (on main, the default branch: brain views " \
           "--write" in out
    assert "warning: edges/_generated_links.yaml is stale: brain sync" in out and "error:" not in out
    request.getfixturevalue("views_strict")   # the owner's opt-in: its views must be fresh
    assert cli.main(["--project", "demo", "check"]) == 1
    out = capsys.readouterr().out
    assert "error: notes/graph/nodes/_generated_links.yaml is stale on main, the default branch" in out
    assert "error: notes/graph/edges/_generated_links.yaml is stale on main, the default branch" in out
    run_git(repo, "checkout", "-q", "-b", "feat")   # a branch need not hold them fresh (brain.views)
    assert cli.main(["--project", "demo", "check"]) == 0
    out = capsys.readouterr().out
    assert "views: 2 stale here (notes/graph/nodes/_generated_links.yaml, notes/graph/edges/_generated_links.yaml)" \
        in out and "error:" not in out


ENGINE = {   # another repo of the project, with no store: its code is described by the store of the repo "demo"
    "README.md": "# engine\n\nThe core lives in src/eng/core.py.\n\n## Hooks\n\nNothing named.\n",
    "pyproject.toml": '[tool.setuptools.packages.find]\nwhere = ["src"]\n',
    "src/eng/__init__.py": "", "src/eng/core.py": "def run():\n    pass\n", "src/eng/other.py": "X = 1\n",
    "src/eng/hooks/start.sh": "echo hi\n",   # the source the store's repo renders into plugins/core/hooks/
    "docs/specs/s.md": "# Not the store's spec\n",
    "tests/test_core.py": "from eng.core import run\n\n\ndef test_run():\n    run()\n",
    "tests/test_start.py": 'import subprocess\n\n\ndef test_start():\n    subprocess.run(["bash", "start.sh"])\n',
    "tests/test_none.py": "def test_x():\n    pass\n",
}
CODED = NODES + """\
- {id: "code:engine:src/eng/core.py", type: CodeRef, status: active, title: "core"}
- {id: feat-run, type: WorkItem, status: todo, title: "Run"}
"""
CODED_EDGES = '- {from: feat-run, to: "code:engine:src/eng/core.py", type: implemented_by}\n'


def test_another_repo_of_the_project_is_derived_against_the_store():
    home = _tree()
    hand, edges = graph._yaml().safe_load(CODED), graph._yaml().safe_load(CODED_EDGES)
    lk = links.derive(mem(ENGINE, "engine"), "engine", "notes/graph", hand=hand, hand_edges=edges, home=home)
    by = {n["id"]: n for n in lk.nodes}
    got = {(e["from"], e["to"]): e["type"] for e in lk.edges}
    t = "test:engine:tests/"
    assert got[("feat-run", t + "test_core.py")] == "tested_by"   # through its CodeRef of this repo
    assert got[("hook-start", t + "test_start.py")] == "tested_by"   # its rendered script, found by hooks/start.sh
    assert got[("feat-run", "doc:engine:README.md::engine")] == "documented_in"
    assert not [s for s, d in got if s in ("plugin-core", "skill-close", "spec-s")]   # anchors are the home repo's
    assert lk.specs == {} and "docs/specs/s.md" in lk.docs   # a spec here is a doc: spec-s anchors the home's
    assert by[t + "test_none.py"] and t + "test_none.py" not in lk.tested
    assert links.coded_repos(hand) == {"demo", "engine"}
    # each node says its anchor is a path of that repo, written before the anchor; the home's nodes say nothing
    assert {n.get("repo") for n in lk.nodes} == {"engine"}
    assert graph.render_node(by[t + "test_core.py"]).splitlines()[1:3] == [
        "   title: tests/test_core.py,", "   repo: engine,"]
    assert not [n for n in links.derive(home, "demo").nodes if "repo" in n]


def test_audit_measures_a_repo_without_a_store_against_the_one_whose_coderefs_name_it():
    t = _tree()
    demo = mem({**{p: t.text(p) for p in t.files}, "notes/graph/nodes/work.yaml": CODED,
                "notes/graph/edges/work.yaml": CODED_EDGES}, "demo")
    root = Path("/m")
    p = projects.Project("demo", root / "demo", [root / "demo" / "notes" / "graph"])
    res = audit.measure(p, [projects.Repo("demo", root / "demo"), projects.Repo("engine", root / "engine")],
                        {"demo": demo, "engine": mem(ENGINE, "engine")})
    assert res["linked"]["engine"] == ("notes/graph", ["Doc", "Test", "Workflow"], "demo")
    eng = next(r for r in res["repos"] if r["name"] == "engine")
    got = {(f["check"], f["unit"]) for f in eng["findings"] if f["check"] in ("doc.links", "test.links")}
    assert got == {("test.links", "tests/test_none.py"), ("doc.links", "docs/specs/s.md")}   # README names core.py
    assert not {x["check"] for x in eng["not_measured"]} & {"doc.links", "test.links"}
    # a repo no CodeRef names stays unmeasured, with the reason
    res = audit.measure(projects.Project("demo", root / "demo", [root / "demo" / "notes" / "graph"]),
                        [projects.Repo("demo", root / "demo"), projects.Repo("engine", root / "engine")],
                        {"demo": _tree(), "engine": mem(ENGINE, "engine")})
    eng = next(r for r in res["repos"] if r["name"] == "engine")
    assert "no CodeRef of the project's store names it" in {x["check"]: x["owner"]
                                                            for x in eng["not_measured"]}["doc.links"]


def test_sync_derives_the_other_repos_a_coderef_names_at_their_committed_state(tmp_path, monkeypatch, make_repo,
                                                                                capsys):
    nodes = NODES.replace("code:demo:p/a.py", "code:engine:src/eng/core.py")
    demo = make_repo("demo", {"notes/graph/schema.yaml": SCHEMA, "notes/graph/nodes/work.yaml": nodes,
                              "notes/graph/edges.yaml": '- {from: wi-a, to: "code:engine:src/eng/core.py", '
                                                        'type: implemented_by}\n',
                              "README.md": "# demo\n\nAbout wi-b.\n"})
    engine = make_repo("engine", ENGINE)
    (engine / "tests" / "test_late.py").write_text("def test_late():\n    pass\n", encoding="utf-8")   # not committed
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {demo.as_posix()}, repos: [., ../engine, ../gone]}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph", lambda root, store, *a: 0)
    assert cli.main(["--project", "demo", "sync"]) == 0
    assert "links graph:" in capsys.readouterr().out
    ids = [n["id"] for n in graph.load_yaml_list(demo / "notes" / "graph" / "nodes" / links.GENERATED)]
    assert "test:engine:tests/test_core.py" in ids and "doc:engine:README.md::engine" in ids
    assert "test:engine:tests/test_late.py" not in ids   # its committed state, as brain audit reads it
    edges = graph.load_yaml_list(demo / "notes" / "graph" / "edges" / links.GENERATED)
    assert {"from": "wi-a", "to": "test:engine:tests/test_core.py", "type": "tested_by"} in edges
    assert cli.main(["--project", "demo", "check"]) == 0
    assert "stale" not in capsys.readouterr().out
    # a CodeRef of a registered repo whose checkout is not here: left out, and said
    (demo / "notes" / "graph" / "nodes" / "more.yaml").write_text(
        '- {id: "code:gone:x.py", type: CodeRef, status: active, title: x}\n', encoding="utf-8")
    assert cli.main(["--project", "demo", "sync"]) == 0
    assert "not on this machine, left out: gone" in capsys.readouterr().out


LINKED = """\
- {id: repo-demo, type: Repo, status: active, title: demo}
- {id: repo-engine, type: Repo, status: active, title: engine}
- {id: wi-a, type: WorkItem, status: todo, title: "A"}
- {id: "code:engine:eng/core.py", type: CodeRef, status: active, title: core}
"""


@pytest.mark.parametrize("where", ["main", "worktree"])
def test_check_reads_the_other_repos_anchors_in_their_checkout(where, tmp_path, monkeypatch, make_repo, capsys):
    """research_graph check resolves the Doc, Test and Workflow anchors of another repo in its checkout, found as
    brain audit finds it: from the root, else from its main checkout (from a worktree, ../engine is not a sibling)."""
    demo = make_repo("demo", {"notes/graph/schema.yaml": SCHEMA.replace("[WorkItem,", "[WorkItem, Repo,")
                              .replace("[specified_by,", "[implemented_by, specified_by,"),
                              "notes/graph/nodes/work.yaml": LINKED,
                              "notes/graph/edges.yaml": '- {from: wi-a, to: "code:engine:eng/core.py", '
                                                        'type: implemented_by}\n',
                              "README.md": "# demo\n\nAbout wi-a.\n"})
    engine = make_repo("engine", {**ENGINE, ".github/workflows/ci.yml": "jobs:\n  test:\n    steps:\n"
                                                                        "      - run: pytest tests\n"})
    root = demo
    if where == "worktree":
        root = tmp_path / "wts" / "demo-wt"
        run_git(demo, "worktree", "add", "-q", "-b", "side", str(root))
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}, repos: [., ../engine]}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    assert cli.main(["--project", "demo", "sync", "--offline"]) == 0
    nodes = graph.load_yaml_list(root / "notes" / "graph" / "nodes" / links.GENERATED)
    of = {n["id"]: n.get("repo") for n in nodes}
    assert of["doc:engine:docs/specs/s.md::not-the-store-s-spec"] == "engine" and of["doc:demo:README.md::demo"] is None
    assert of["workflow:engine:.github/workflows/ci.yml::test"] == "engine"
    capsys.readouterr()
    assert cli.main(["--project", "demo", "check"]) == 0   # docs/specs/s.md, tests/, ci.yml: engine's files alone
    out = capsys.readouterr()
    assert f"--repo-path engine={engine.resolve()}" in out.out and "graph-check OK" in out.out
    assert "not checked" not in out.out and "anchor file missing" not in out.err
    # a file gone from engine's checkout: its anchor fails, named with its repo
    (engine / "docs" / "specs" / "s.md").unlink()
    assert cli.main(["--project", "demo", "check"]) == 1
    assert "anchor file missing: docs/specs/s.md (repo engine)" in capsys.readouterr().err
