import ast
import json
import re
import subprocess

import pytest

from brain import cli, codeindex, codemap, projects
from conftest import run_git

CORE = """\
def go():
    return 1


class Engine:
    def run(self):
        return go()


LIMIT = 3


def helper():
    def go():
        return 0
    return go()
"""
CLI = "from lab import core\n\n\ndef main():\n    return core.go()\n\n\ndef other():\n    return 0\n"
SCHEMA = """\
node_types: [Feature, WorkItem, ADR, Spec, DDR, CodeRef, Repo, Doc, Test, Workflow]
edge_types: [implemented_by, delivers, decided_by, specified_by, about, part_of, documented_in, tested_by, runs,
             supersedes]
statuses: [active, retired, todo, doing, done, have, partial, planned, "no", pending, answered, superseded]
layers:
  work: [WorkItem, Spec]
  features: [Feature]
  decisions: [ADR, DDR]
  code: [CodeRef, Repo]
  docs_tests: [Doc, Test, Workflow]
"""
REFS = ["lab/core.py::go", "lab/core.py::Engine", "lab/core.py::Engine.run", "lab/core.py::LIMIT",
        "lab/core.py::gone", "lab/cli.py::main", "lab/cli.py", "README.md"]
CODE = ("- {id: repo-lab, type: Repo, status: active, title: lab}\n"
        "- {id: repo-other, type: Repo, status: active, title: other}\n"
        + "".join(f'- {{id: "code:lab:{r}", type: CodeRef, status: active, title: x}}\n' for r in REFS)
        + '- {id: "code:other:x.py", type: CodeRef, status: active, title: x}\n'
        + '- {id: "code:lab:lab/old.py", type: CodeRef, status: retired, title: x}\n')
LAB = {"README.md": "# Lab\n", "src/lab/__init__.py": "", "src/lab/core.py": CORE, "src/lab/cli.py": CLI,
       "notes/graph/schema.yaml": SCHEMA, "notes/graph/edges.yaml": "[]\n", "notes/graph/nodes/code.yaml": CODE}


def md_answer(rows: list[dict]) -> str:
    """GitNexus's cypher answer: a markdown table (``[]`` when nothing matched) and its next-step hint."""
    if not rows:
        return "[]"
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "| " + " | ".join("---" for _ in keys) + " |"]
    lines += ["| " + " | ".join("" if r[k] is None else str(r[k]) for k in keys) + " |" for r in rows]
    return json.dumps({"markdown": "\n".join(lines), "row_count": len(rows)}, indent=2) + \
        "\n\n---\n**Next:** To explore a result symbol, use context()."


def index_nodes(repo, sha) -> tuple[list[dict], list[tuple[str, str]]]:
    """What GitNexus holds of ``repo`` at ``sha``, from its Python files by AST: File, Function, Class, Method (and
    HAS_METHOD), Variable; nested functions are Functions too."""
    nodes, members = [], []
    files = run_git(repo, "ls-tree", "-r", "--name-only", sha).split()
    for f in files:
        if not f.endswith(".py"):
            continue
        nodes.append({"id": f"File:{f}", "name": f.rsplit("/", 1)[-1], "label": "File", "path": f,
                      "startLine": None, "endLine": None})
        tree = ast.parse(run_git(repo, "show", f"{sha}:{f}"))
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.ClassDef):
                nodes.append({"id": f"Class:{f}:{stmt.name}", "name": stmt.name, "label": "Class", "path": f,
                              "startLine": stmt.lineno, "endLine": stmt.end_lineno})
                for m in stmt.body:
                    if isinstance(m, ast.FunctionDef):
                        mid = f"Method:{f}:{stmt.name}.{m.name}#{len(m.args.args)}"
                        nodes.append({"id": mid, "name": m.name, "label": "Method", "path": f,
                                      "startLine": m.lineno, "endLine": m.end_lineno})
                        members.append((f"Class:{f}:{stmt.name}", mid))
            elif isinstance(stmt, ast.FunctionDef) and not any(stmt in c.body for c in ast.walk(tree)
                                                               if isinstance(c, ast.ClassDef)):
                nodes.append({"id": f"Function:{f}:{stmt.name}" + ("" if stmt in tree.body else f"@{stmt.lineno}"),
                              "name": stmt.name, "label": "Function", "path": f, "startLine": stmt.lineno,
                              "endLine": stmt.end_lineno})
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    nodes.append({"id": f"Variable:{f}:{t.id}", "name": t.id, "label": "Variable", "path": f,
                                  "startLine": stmt.lineno, "endLine": stmt.end_lineno})
    return nodes, members


class Nexus:
    """GitNexus for brain.codemap and brain.impact: its registry (/api/repos) and its MCP cypher tool, answering
    the queries those modules send from an index built by AST at each repo's indexed commit. ``calls``: (caller,
    callee, confidence) edges."""

    def __init__(self, monkeypatch, repos: dict, calls=(), up=True):
        self.repos, self.calls, self.up, self.queries, self.built = repos, list(calls), up, [], {}
        monkeypatch.setattr(codeindex, "_http", self.http)
        monkeypatch.setattr(codeindex, "_mcp_tool", self.mcp)

    def http(self, method, url, body=None, timeout=10.0):
        if not self.up:
            return 0, "[WinError 10061] connection refused"
        assert (method, url.split("4747", 1)[1]) == ("GET", "/api/repos")
        return 200, [{"name": n, "path": f"/data/gitnexus/repos/{n}", "lastCommit": sha, "branch": "main"}
                     for n, (_, sha) in self.repos.items()]

    def mcp(self, url, name, arguments, timeout=120.0):
        assert name == "cypher"
        q, repo = arguments["query"], arguments["repo"]
        self.queries.append(q)
        if repo not in self.built:
            self.built[repo] = index_nodes(*self.repos[repo])
        answer = next(h for key, h in ((" (f:File) ", self.files), ("count(*)", self.count),
                                       ("WHERE n.filePath IN", self.nodes), ("(c:Class)", self.members),
                                       ("'CALLS'", self.callers)) if key in q)
        return md_answer(answer(q, *self.built[repo])), ""

    @staticmethod
    def listed(q: str, after: str = "IN") -> set[str]:
        """The quoted strings of the first list after ``after`` in a query."""
        return set(re.findall(r"'((?:[^'\\]|\\.)*)'", q.split(f"{after} [", 1)[1].split("]", 1)[0]))

    def files(self, q, nodes, members):
        return [{"path": n["path"]} for n in nodes if n["label"] == "File"]

    def count(self, q, nodes, members):
        return [{"n": sum(n["label"] in codemap.SYMBOLS for n in nodes)}]

    def nodes(self, q, nodes, members):
        return [dict(n) for n in nodes if n["path"] in self.listed(q)]

    def members(self, q, nodes, members):
        return [{"class": c, "member": m} for c, m in members if c.split(":")[1] in self.listed(q)]

    def callers(self, q, nodes, members):
        floor, ids = float(re.search(r"r.confidence >= ([\d.]+)", q).group(1)), self.listed(q, "n.id IN")
        by_id = {n["id"]: n for n in nodes}
        return [{"id": a, "name": by_id[a]["name"], "label": by_id[a]["label"], "path": by_id[a]["path"],
                 "callee": b} for a, b, c in self.calls if b in ids and c >= floor]


@pytest.fixture
def lab(make_repo, tmp_path, monkeypatch):
    """The lab repo with its store (the project demo), indexed at its first commit; GitNexus is the stack."""
    repo = make_repo("lab", LAB)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo:\n  root: {repo.as_posix()}\n  code_index: [.]\n  stacks:\n    gitnexus:\n"
                   "      start: [docker, compose, up, -d]\n"
                   "      health: {urls: ['http://127.0.0.1:4747/api/health']}\n"
                   "      index: {api: 'http://127.0.0.1:4747', container: gitnexus}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return repo


def _sha(repo, ref="HEAD"):
    return run_git(repo, "rev-parse", ref).strip()


def test_each_coderef_resolves_to_its_node_with_the_coverage(lab, monkeypatch, capsys):
    Nexus(monkeypatch, {"lab": (lab, _sha(lab))})
    assert cli.main(["--project", "demo", "code-map"]) == 0
    out = capsys.readouterr().out
    data = codemap.read("demo")
    refs = data["refs"]
    got = {k[9:]: (r["label"], r["node"], r["path"], r["start"], r["end"], r["why"] != "") for k, r in refs.items()
           if k.startswith("code:lab:")}
    assert got["lab/core.py::go"] == ("Function", "Function:src/lab/core.py:go", "src/lab/core.py", 1, 2, False)
    assert got["lab/core.py::Engine"][:2] == ("Class", "Class:src/lab/core.py:Engine")
    assert got["lab/core.py::Engine.run"][:2] == ("Method", "Method:src/lab/core.py:Engine.run#1")
    assert got["lab/core.py::LIMIT"][:2] == ("Variable", "Variable:src/lab/core.py:LIMIT")   # an assignment
    assert got["lab/cli.py"][:3] == ("File", "File:src/lab/cli.py", "src/lab/cli.py")
    assert got["lab/core.py::gone"] == ("File", "File:src/lab/core.py", "src/lab/core.py", None, None, True)
    assert refs["code:lab:lab/core.py::gone"]["why"] == "gone: not in the index of src/lab/core.py (the File stands in)"
    assert got["README.md"][5] and "not in the index" in refs["code:lab:README.md"]["why"]
    assert refs["code:other:x.py"]["why"] == "not indexed (brain index other)"
    assert "code:lab:lab/old.py" not in refs                           # retired: not mapped
    lab_ = data["repos"]["lab"]
    # 7 symbols (go, Engine, Engine.run, helper, its nested go, main, other), 4 named; files: core.py and cli.py of 3
    assert (lab_["symbols"], lab_["symbols_with_ref"], lab_["files"], lab_["files_with_ref"]) == (7, 4, 3, 2)
    assert (lab_["refs"], lab_["resolved"]) == (8, 6)
    assert "lab (main@" in out and "6/8 CodeRef(s) resolved; coverage: symbols 4/7 (57.1 %), files 2/3 (66.7 %)" in out
    assert "other: 1 CodeRef(s), none resolved: not indexed (brain index other)" in out
    assert "  code:lab:README.md: not in the index" in out and "code:other:x.py:" not in out   # said once, per repo
    assert out.rstrip().endswith("demo.json")


def test_gitnexus_down_writes_nothing_and_exits_1(lab, monkeypatch, capsys):
    Nexus(monkeypatch, {"lab": (lab, _sha(lab))}, up=False)
    assert cli.main(["--project", "demo", "code-map"]) == 1
    assert "gitnexus does not answer at http://127.0.0.1:4747; brain up gitnexus starts it" in capsys.readouterr().out
    assert codemap.read("demo") == {}


def test_the_json_view_and_a_project_without_the_stack(lab, tmp_path, monkeypatch, capsys):
    Nexus(monkeypatch, {"lab": (lab, _sha(lab))})
    assert cli.main(["--project", "demo", "code-map", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["code_map"] == codemap.VERSION
    (tmp_path / "projects.yaml").write_text(f"demo: {{root: {lab.as_posix()}}}\n", encoding="utf-8")
    assert cli.main(["--project", "demo", "code-map"]) == 2
    assert "no stack declares index:" in capsys.readouterr().err


def test_cypher_answers_are_read_as_rows():
    assert codemap.table(md_answer([{"id": "a", "start": 3, "end": None}])) == ([{"id": "a", "start": 3,
                                                                                  "end": None}], "")
    assert codemap.table("[]\n\n---\n**Next:** ...") == ([], "")
    assert codemap.table('{"error": "Prepare failed: Parser exception"}')[1] == "Prepare failed: Parser exception"
    assert codemap.table("Error: no repo")[1].startswith("not a cypher answer")
    assert codemap.lit("it's a\\b") == "'it\\'s a\\\\b'"


def test_a_one_part_symbol_is_the_top_level_definition():
    nodes = [{"id": "F", "name": "go", "label": "Function", "path": "a.py", "startLine": 10, "endLine": 12},
             {"id": "N", "name": "go", "label": "Function", "path": "a.py", "startLine": 2, "endLine": 3},
             {"id": "O", "name": "outer", "label": "Function", "path": "a.py", "startLine": 1, "endLine": 4},
             {"id": "M", "name": "go", "label": "Method", "path": "a.py", "startLine": 6, "endLine": 7},
             {"id": "C", "name": "K", "label": "Class", "path": "a.py", "startLine": 5, "endLine": 8}]
    assert codemap.match("go", "a.py", nodes, {"C": {"M"}})[0]["id"] == "F"      # not nested, not a method
    assert codemap.match("K.go", "a.py", nodes, {"C": {"M"}})[0]["id"] == "M"
    assert codemap.match("K.stop", "a.py", nodes, {"C": {"M"}}) == (None, "K.stop: no member stop of a class K "
                                                                         "in a.py")
    assert codemap.file_of("lab/x.py", {"src/lab/x.py", "lab/x.py"}) == "src/lab/x.py"   # code-check's order


def test_the_map_is_machine_local_under_the_brain_home(brain_home):
    assert codemap.map_file("demo") == brain_home / "code-map" / "demo.json"
    assert codemap.read("demo") == {}


def test_a_worktree_of_the_project_maps_the_same_refs(lab, tmp_path, monkeypatch, capsys):
    """brain code-map from a worktree of the project's checkout: its stores there."""
    wt = tmp_path / "wt"
    run_git(lab, "worktree", "add", "-q", str(wt))
    Nexus(monkeypatch, {"lab": (lab, _sha(lab))})
    monkeypatch.chdir(wt)
    assert cli.main(["code-map"]) == 0
    assert codemap.read("demo")["repos"]["lab"]["resolved"] == 6
    assert projects.get("demo", wt).stores[0].parent.parent == wt
    subprocess.run(["git", "-C", str(lab), "worktree", "remove", "--force", str(wt)], capture_output=True)
