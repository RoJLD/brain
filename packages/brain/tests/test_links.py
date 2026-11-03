import json
from pathlib import Path

from brain import audit, cli, graph, links, projects

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


def test_audit_measures_doc_and_test_links_where_the_store_takes_them():
    res = audit.measure(projects.Project("demo", Path("/m/demo"), [Path("/m/demo/notes/graph")]),
                        [projects.Repo("demo", Path("/m/demo"))], {"demo": _tree()})
    r = res["repos"][0]
    got = {(f["check"], f["unit"]): f["severity"] for f in r["findings"] if f["check"] in ("doc.links", "test.links")}
    assert got == {("doc.links", "docs/guide.md"): "P2", ("doc.links", "docs/specs/t.md"): "P2",
                   ("test.links", "tests/unit/x.Tests.ps1"): "P2"}
    assert {x["check"] for x in r["not_measured"]} & {"doc.links", "test.links"} == set()
    assert res["linked"] == {"demo": ("notes/graph", ["Doc", "Test", "Workflow"])}
    # a store without the types, and a repo with no store: still listed as not measured, with the reason
    bare = _measure({"README.md": "# x\n" + "line\n" * 12, "notes/graph/schema.yaml": "node_types: [WorkItem]\n",
                     "src/q.py": "def f():\n    pass\n"})
    owners = {x["check"]: x["owner"] for x in bare["repos"][0]["not_measured"]}
    assert owners["doc.links"] == "notes/graph has no Doc type" and owners["test.links"] == "notes/graph has no Test type"
    none = _measure({"README.md": "# x\n" + "line\n" * 12})
    assert {x["check"]: x["owner"] for x in none["repos"][0]["not_measured"]}["doc.links"] == \
        "no store of its own to hold the links"
    assert audit.CHECKS["test.links"].scout == "never" and audit.RULESET >= 2   # 2 brought doc.links and test.links


def test_sync_writes_the_links_and_check_warns_when_stale(tmp_path, monkeypatch, make_repo, capsys):
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
    assert cli.main(["--project", "demo", "check"]) == 0
    out = capsys.readouterr().out
    assert "warning: nodes/_generated_links.yaml is stale: brain sync" in out
    assert "warning: edges/_generated_links.yaml is stale: brain sync" in out
