"""Tests linked automatically (wi-brain-test-links-auto) and coverage measured (wi-brain-test-coverage): tested_by
from a test's own imports, a CodeRef's symbol narrowed to the tests that name it or that the coverage contexts saw
run it, the store's coverage summary (brain.testcov), audit's test.coverage and feature.tests, FEATURES.md's
coverage cell."""

import json
import sqlite3
from pathlib import Path

import pytest

from brain import audit, cli, features, links, projects, testcov

from test_inventory import mem

SCHEMA = ("node_types: [WorkItem, Feature, CodeRef, Doc, Test, Workflow]\n"
          "edge_types: [implemented_by, tested_by, documented_in, part_of, runs]\n"
          "statuses: [active, todo, have, partial, planned]\n")
NODES = """\
- {id: feat-run, type: Feature, status: have, title: "Run a job", props: {repo: demo, domain: jobs}}
- {id: feat-check, type: Feature, status: have, title: "Check a secret", props: {repo: demo, domain: jobs}}
- {id: feat-core, type: Feature, status: have, title: "The core", props: {repo: demo, domain: jobs}}
- {id: feat-lonely, type: Feature, status: partial, title: "Untested", props: {repo: demo, domain: jobs}}
- {id: feat-later, type: Feature, status: planned, title: "Not yet", props: {repo: demo, domain: jobs}}
- {id: feat-hub, type: Feature, status: have, title: "Owned by the hub", props: {repo: hub, domain: jobs}}
- {id: feat-data, type: Feature, status: have, title: "A data file", props: {repo: demo, domain: jobs}}
- {id: "code:demo:p/cli.py::cmd_run_job", type: CodeRef, status: active, title: "run job"}
- {id: "code:demo:p/guards.py::check_secret", type: CodeRef, status: active, title: "secret"}
- {id: "code:demo:p/core.py", type: CodeRef, status: active, title: "core"}
- {id: "code:demo:p/lonely.py", type: CodeRef, status: active, title: "lonely"}
"""
EDGES = """\
- {from: feat-run, to: "code:demo:p/cli.py::cmd_run_job", type: implemented_by}
- {from: feat-check, to: "code:demo:p/guards.py::check_secret", type: implemented_by}
- {from: feat-core, to: "code:demo:p/core.py", type: implemented_by}
- {from: feat-lonely, to: "code:demo:p/lonely.py", type: implemented_by}
- {from: feat-hub, to: "code:demo:p/lonely.py::alone", type: implemented_by}
- {from: feat-data, to: "code:demo:pyproject.toml", type: implemented_by}
"""
CLI = """\
from p import core


def cmd_run_job(args):
    return core.go()


def cmd_other(args):
    return 0


def main(argv):
    return {"run": cmd_run_job, "other": cmd_other}[argv[0]](argv)
"""


def _files(**extra) -> dict:
    files = {
        "notes/graph/schema.yaml": SCHEMA, "notes/graph/nodes/work.yaml": NODES,
        "notes/graph/edges/work.yaml": EDGES,
        "README.md": "# demo\n\n" + "A line of the readme.\n" * 12,
        "pyproject.toml": '[tool.setuptools.packages.find]\nwhere = ["src"]\n'
                          '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        "src/p/__init__.py": "", "src/p/cli.py": CLI,
        "src/p/core.py": "def go():\n    return 1\n",
        "src/p/guards.py": "def check_secret(cmd):\n    return 'key' in cmd\n\n\ndef check_other(cmd):\n"
                           "    return False\n",
        "src/p/lonely.py": "def alone():\n    return 2\n",
        # named after core.py: brain audit's evidence for core.py is this test alone ('name')
        "tests/test_core.py": "from p.core import go\n\n\ndef test_go():\n    assert go() == 1\n",
        # imports core.py too: the import derivation adds it
        "tests/test_flow.py": "from p import core\n\n\ndef test_flow():\n    assert core.go()\n",
        # import p.cli: the run job subcommand (its words) and another one
        "tests/test_run.py": "from p import cli\n\n\ndef test_run():\n    assert cli.main(['run', 'job'])\n",
        "tests/test_other.py": "from p import cli\n\n\ndef test_other():\n    assert cli.main(['other']) == 0\n",
        # imports guards: one names the secret check (its words), one never does
        "tests/test_guards.py": "from p import guards\n\n\ndef test_secret():\n"
                                "    assert not guards.check_other('a secret')  # the secret check\n",
        "tests/test_guards_more.py": "from p import guards\n\n\ndef test_more():\n"
                                     "    assert not guards.check_other('x')\n",
    }
    files.update(extra)
    return files


def _tested(lk) -> dict[str, set]:
    out: dict[str, set] = {}
    for e in lk.edges:
        if e["type"] == "tested_by":
            out.setdefault(e["from"], set()).add(e["to"].rsplit("/", 1)[-1])
    return out


def test_imports_add_tests_and_a_symbol_keeps_the_tests_that_name_it():
    lk = links.derive(mem(_files(), "demo"), "demo")
    got = _tested(lk)
    # test_core.py is core.py's 'name' evidence (the audit's strongest); test_flow.py imports it too
    assert got["feat-core"] == {"test_core.py", "test_flow.py"}
    # both tests import p.cli: only the one that runs the run job subcommand counts for cmd_run_job
    assert got["feat-run"] == {"test_run.py"}
    # check_secret: the test that names the secret check, not the other guard's
    assert got["feat-check"] == {"test_guards.py"}
    assert "feat-lonely" not in got   # no test imports, names or runs lonely.py
    assert links.names_symbol.__doc__ and "cmd_" in links.names_symbol.__doc__


def _summary(tests_of_cli: dict, tests_of_guards: dict | None = None) -> str:
    files = {"src/p/cli.py": {"statements": 9, "covered": 9, "percent": 100.0, "tests": tests_of_cli},
             "src/p/core.py": {"statements": 2, "covered": 2, "percent": 100.0},
             "src/p/lonely.py": {"statements": 2, "covered": 0, "percent": 0.0},
             "src/p/guards.py": {"statements": 4, "covered": 3, "percent": 75.0, "tests": tests_of_guards or {}}}
    return testcov.render({"version": 1, "repo": "demo", "commit": "abc1234", "dirty": False,
                           "measured": "2026-11-03", "tool": "coverage 7", "statements": 17, "covered": 14,
                           "percent": 82.4, "files": files})


def test_coverage_contexts_decide_a_symbol_when_the_store_has_them():
    # the contexts saw test_other.py run cmd_run_job (say other calls it) and test_run.py not: they win over the
    # words; a test that names the symbol itself still counts; a test that does not import the file never does
    cov = _summary({"tests/test_other.py": ["cmd_other", "cmd_run_job"], "tests/test_run.py": ["main"],
                    "tests/test_far.py": ["cmd_run_job"]},
                   {"tests/test_guards_more.py": ["check_other", "check_secret"]})
    files = _files(**{"notes/graph/coverage/demo.json": cov,
                      "tests/test_far.py": "def test_far():\n    pass\n",
                      "tests/test_named.py": "from p.cli import cmd_run_job\n\n\ndef test_named():\n"
                                             "    assert cmd_run_job(None)\n"})
    got = _tested(links.derive(mem(files, "demo"), "demo"))
    assert got["feat-run"] == {"test_other.py", "test_named.py"}
    assert got["feat-check"] == {"test_guards_more.py"}   # the words of test_guards.py no longer count
    assert got["feat-core"] == {"test_core.py", "test_flow.py"}   # a whole file: the static links, unchanged
    assert testcov.ran(json.loads(cov), "src/p/cli.py", "cmd_run_job") == {"tests/test_other.py",
                                                                            "tests/test_far.py"}


def test_functions_map_lines_to_the_outermost_function_or_method():
    src = ("import os\n\n@dec\ndef f():\n    def inner():\n        pass\n    return inner\n\n\n"
           "class C:\n    x = 1\n\n    def m(self):\n        return 2\n")
    fn = testcov.functions(src)
    assert 1 not in fn   # a module body is no function
    assert [fn.get(n) for n in (3, 4, 6, 7)] == ["f", "f", "f", "f"]   # the decorator, a nested function
    assert 11 not in fn and fn[13] == "C.m" and fn[14] == "C.m"   # a class body is no function
    assert testcov.functions("def (:\n") == {}


def _data_file(path: Path, root: Path) -> None:
    """A coverage data file with coverage's own SQLite tables: two test contexts and the import context."""
    db = sqlite3.connect(path)
    db.executescript("create table meta (key text, value text, unique (key));"
                     "create table file (id integer primary key, path text, unique (path));"
                     "create table context (id integer primary key, context text, unique (context));"
                     "create table line_bits (file_id integer, context_id integer, numbits blob,"
                     " unique (file_id, context_id));")
    db.execute("insert into meta values ('version', '7.17.1')")
    db.execute("insert into file values (1, ?)", (str(root / "src" / "p" / "cli.py"),))
    db.execute("insert into file values (2, ?)", (str(root.parent / "elsewhere.py"),))
    db.executemany("insert into context values (?, ?)", [(1, ""), (2, "tests/test_run.py::test_run|run"),
                                                         (3, "tests/test_other.py::test_other|setup")])

    def bits(*lines):
        out = bytearray(max(lines) // 8 + 1)
        for n in lines:
            out[n // 8] |= 1 << (n % 8)
        return bytes(out)
    db.executemany("insert into line_bits values (?, ?, ?)",
                   [(1, 1, bits(1, 4, 8, 12)), (1, 2, bits(5, 13)), (1, 3, bits(9)), (2, 2, bits(1))])
    db.commit()
    db.close()


def test_contexts_and_summary_from_a_coverage_data_file(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "p").mkdir(parents=True)
    (root / "src" / "p" / "cli.py").write_text(CLI, encoding="utf-8")
    data = tmp_path / ".coverage"
    _data_file(data, root)
    ctxs, tool = testcov.contexts(data, root, root)
    assert tool == "7.17.1"
    assert ctxs == {"src/p/cli.py": {5: {"tests/test_run.py"}, 13: {"tests/test_run.py"},
                                     9: {"tests/test_other.py"}}}   # the import context and elsewhere.py left out
    rep = {"files": {"src/p/cli.py": {"summary": {"num_statements": 9}, "executed_lines": [1, 4, 5, 8, 9, 12, 13]}}}
    sm = testcov.summarize([(rep, ctxs, root)], root, "Demo", "abc", day="2026-11-03", tool=tool)
    f = sm["files"]["src/p/cli.py"]
    assert (sm["repo"], sm["statements"], sm["covered"], sm["percent"]) == ("demo", 9, 7, 77.8)
    assert f["tests"] == {"tests/test_other.py": ["cmd_other"], "tests/test_run.py": ["cmd_run_job", "main"]}
    assert testcov.render(sm) == testcov.render(json.loads(testcov.render(sm)))   # sorted, stable
    assert testcov.lines(sm)[0].startswith("demo: 77.8 % of 9 statements (1 files) at abc")
    with pytest.raises(testcov.CoverageError):
        testcov.contexts(tmp_path / "missing" / ".coverage", root, root)


def test_suites_run_where_their_pytest_configuration_is(tmp_path):
    (tmp_path / "packages" / "app").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    (tmp_path / "packages" / "app" / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "setup.cfg").write_text("[metadata]\nname = x\n", encoding="utf-8")   # not pytest's
    got = testcov.suites(tmp_path, ["tests/test_a.py", "tests/unit/test_b.py", "packages/app/tests/test_c.py",
                                    "tools/tests/test_d.py", "tests/x.Tests.ps1"])
    assert got == [("", ["tests", "tools"]), ("packages/app", ["tests"])]


def test_audit_measures_test_coverage_and_feature_tests():
    def measure(files):
        root = Path("/m/demo")
        return audit.measure(projects.Project("demo", root, [root / "notes" / "graph"]),
                             [projects.Repo("demo", root)], {"demo": mem(files, "demo")})["repos"][0]
    r = measure(_files())
    owners = {x["check"]: x["owner"] for x in r["not_measured"]}
    assert owners["test.coverage"] == "no coverage summary in notes/graph (brain coverage --run --write)"
    found = {(f["check"], f["unit"]) for f in r["findings"] if f["check"] in ("feature.tests", "test.coverage")}
    # planned features, tested ones and one whose code is a data file are not findings; a feature another repo
    # owns, with its code here, is one
    assert found == {("feature.tests", "feat-lonely"), ("feature.tests", "feat-hub")}
    r = measure(_files(**{"notes/graph/coverage/demo.json": _summary({})}))
    cov = [f for f in r["findings"] if f["check"] == "test.coverage"]
    assert [(f["unit"], f["severity"]) for f in cov] == [("src/p/lonely.py", "P2")]
    assert "0 % of its 2 statements (coverage at abc1234)" in cov[0]["why"]
    assert "test.coverage" not in {x["check"] for x in r["not_measured"]}
    assert audit.RULESET >= 4 and audit.CHECKS["feature.tests"].scout == "never"


def test_features_md_shows_the_coverage_of_a_features_files():
    t = mem(_files(**{"notes/graph/coverage/demo.json": _summary({})}), "demo")
    m = features.load_tree(t, "notes/graph", "demo")
    assert features.coverage_of(m, "feat-core") == 100.0
    assert features.coverage_of(m, "feat-lonely") == 0.0
    assert features.coverage_of(m, "feat-run") is None   # a symbol: its file's figure would mislead
    text = features.render(m, "demo")
    assert "| Tests |" in text and "100 % covered" in text and "0 % covered" in text


def test_brain_coverage_from_a_data_file_writes_the_summary(tmp_path, monkeypatch, make_repo, capsys):
    root = make_repo("demo", {"src/p/cli.py": CLI, "notes/graph/schema.yaml": SCHEMA})
    monkeypatch.setenv("BRAIN_ROOT", str(root))
    data = tmp_path / ".coverage"
    _data_file(data, root)
    rep = {"files": {str(root / "src" / "p" / "cli.py"): {"summary": {"num_statements": 9},
                                                         "executed_lines": [1, 4, 5, 8, 9, 12, 13]}}}
    monkeypatch.setattr(testcov, "_report", lambda python, d, where, out: rep)   # coverage json, not installed
    monkeypatch.setattr(cli, "_repos", lambda args, r: [projects.Repo("demo", root)])
    monkeypatch.setattr(cli, "_store", lambda args, r: root / "notes" / "graph")
    assert cli.main(["coverage", "--repo", "demo", "--from", str(data), "--write"]) == 0
    out = capsys.readouterr().out
    assert "demo: 77.8 % of 9 statements" in out and "coverage" in out
    kept = json.loads((root / "notes" / "graph" / "coverage" / "demo.json").read_text(encoding="utf-8"))
    assert kept["files"]["src/p/cli.py"]["tests"]["tests/test_run.py"] == ["cmd_run_job", "main"]
    with pytest.raises(SystemExit, match="--run"):
        cli.main(["coverage", "--repo", "demo"])
    with pytest.raises(SystemExit, match="no repo nope"):
        cli.main(["coverage", "--repo", "nope", "--run"])
