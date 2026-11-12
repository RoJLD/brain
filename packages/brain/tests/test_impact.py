import json

import pytest

from brain import cli, diffs, impact
from conftest import run_git
from test_codemap import CORE, LAB, FakeGitNexus, _sha

GRAPH = {
    "notes/graph/nodes/features.yaml": """\
        - {id: feat-all, type: Feature, status: partial, title: All}
        - {id: feat-go, type: Feature, status: planned, title: Go}
        - {id: feat-engine, type: Feature, status: have, title: Engine}
        - {id: feat-cli, type: Feature, status: have, title: CLI}
        """,
    "notes/graph/nodes/work.yaml": """\
        - {id: wi-go, type: WorkItem, status: todo, title: Ship go}
        - {id: wi-old, type: WorkItem, status: done, title: Old}
        - {id: spec-go, type: Spec, status: active, title: Go spec, anchor: "docs/spec.md#top"}
        - {id: adr-old, type: ADR, status: superseded, title: Old decision}
        - {id: adr-new, type: ADR, status: active, title: New decision}
        - {id: ddr-go, type: DDR, status: pending, title: Which go?}
        """,
    "notes/graph/nodes/_generated_links.yaml": """\
        - {id: "doc:lab:docs/guide.md::core", type: Doc, status: active, title: "docs/guide.md § Core",
           anchor: "docs/guide.md#core", props: {paths: [src/lab/core.py]}}
        - {id: "doc:lab:README.md::cli", type: Doc, status: active, title: "README.md § CLI", anchor: "README.md#cli"}
        - {id: "doc:lab:README.md::other", type: Doc, status: active, title: "README.md § Other",
           anchor: "README.md#other", props: {paths: [src/lab/other.py]}}
        - {id: "test:lab:tests", type: Test, status: active, title: "tests/", anchor: "tests#tests"}
        - {id: "test:lab:tests/test_core.py", type: Test, status: active, title: t, anchor: "tests/test_core.py#tests",
           props: {framework: pytest, covers: [src/lab/core.py]}}
        - {id: "test:lab:tests/test_cli.py", type: Test, status: active, title: t, anchor: "tests/test_cli.py#tests",
           props: {framework: pytest, covers: [src/lab/cli.py]}}
        - {id: "test:lab:tests/test_misc.py", type: Test, status: active, title: t, anchor: "tests/test_misc.py#tests",
           props: {framework: pytest, covers: [src/lab/misc.py]}}
        - {id: "test:lab:tests/Lab.Tests.ps1", type: Test, status: active, title: t, anchor: "tests/Lab.Tests.ps1#tests",
           props: {framework: pester, covers: [src/lab/core.py]}}
        - {id: "workflow:lab:.github/workflows/ci.yml::test", type: Workflow, status: active, title: "ci.yml test",
           anchor: ".github/workflows/ci.yml#test"}
        - {id: "workflow:lab:.github/workflows/ci.yml::lint", type: Workflow, status: active, title: "ci.yml lint",
           anchor: ".github/workflows/ci.yml#lint"}
        """,
    "notes/graph/edges/features.yaml": """\
        - {from: feat-go, to: "code:lab:lab/core.py::go", type: implemented_by}
        - {from: feat-engine, to: "code:lab:lab/core.py::Engine", type: implemented_by}
        - {from: feat-cli, to: "code:lab:lab/cli.py::main", type: implemented_by}
        - {from: feat-go, to: feat-all, type: part_of}
        - {from: wi-go, to: feat-go, type: delivers}
        - {from: wi-old, to: feat-go, type: delivers}
        - {from: feat-go, to: spec-go, type: specified_by}
        - {from: feat-go, to: adr-old, type: decided_by}
        - {from: adr-new, to: adr-old, type: supersedes}
        - {from: ddr-go, to: wi-go, type: about}
        - {from: feat-cli, to: "doc:lab:README.md::cli", type: documented_in}
        - {from: feat-go, to: "test:lab:tests/test_core.py", type: tested_by}
        - {from: feat-go, to: "test:lab:tests/test_misc.py", type: tested_by}
        - {from: "test:lab:tests/test_core.py", to: "test:lab:tests", type: part_of}
        - {from: "test:lab:tests/test_cli.py", to: "test:lab:tests", type: part_of}
        - {from: "workflow:lab:.github/workflows/ci.yml::test", to: "test:lab:tests", type: runs}
        """,
}
GO2 = CORE.replace("def go():\n    return 1", "def go():\n    return 2")
HELPER2 = GO2.replace("        return 0", "        return -1")
CALLS = [("Function:src/lab/cli.py:main", "Function:src/lab/core.py:go", 0.85),
         ("Function:src/lab/cli.py:other", "Function:src/lab/core.py:go", 0.53),    # a guess by name
         ("Method:src/lab/core.py:Engine.run#1", "Function:src/lab/core.py:go", 0.85)]


@pytest.fixture
def lab(make_repo, tmp_path, monkeypatch):
    """The demo project's lab repo (its store has features, items, decisions, docs, tests and CI), on a feature branch
    from main."""
    repo = make_repo("lab", {**LAB, **GRAPH})
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo:\n  root: {repo.as_posix()}\n  code_index: [.]\n  stacks:\n    gitnexus:\n"
                   "      start: [docker, compose, up, -d]\n"
                   "      health: {urls: ['http://127.0.0.1:4747/api/health']}\n"
                   "      index: {api: 'http://127.0.0.1:4747', container: gitnexus}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(repo, "checkout", "-q", "-b", "feature")
    return repo


def _impact(capsys, repo, *args):
    rc = cli.main(["impact", *args, "--repo-dir", str(repo), "--json"])
    return rc, json.loads(capsys.readouterr().out)


def _ids(rows, key="id"):
    return [r[key] for r in rows]


def _chain(lab, make_repo, monkeypatch):
    """GitNexus up, lab indexed at main; the change edits go and helper's nested go, and adds a test module."""
    gn = FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, CALLS)
    make_repo.write(lab, {"src/lab/core.py": HELPER2, "tests/test_new.py": "def test_x():\n    pass\n"})
    return gn


def test_the_chain_from_touched_symbols_to_the_coderefs(lab, make_repo, monkeypatch, capsys):
    gn = _chain(lab, make_repo, monkeypatch)
    rc, d = _impact(capsys, lab)
    assert (rc, d["mode"], d["index"], d["new"]) == (0, "gitnexus", _sha(lab, "main"), "worktree")
    assert [(s["name"], s["lines"]) for s in d["symbols"]] == [("go", [1, 2]), ("helper", [13, 16]),
                                                              ("go", [14, 15])]
    assert sorted((c["name"], c["level"]) for c in d["callers"]) == [("main", 1), ("run", 1)]   # not the guess
    assert [(t["ref"], t["how"]) for t in d["coderefs"]] == [
        ("code:lab:lab/cli.py::main", "caller"), ("code:lab:lab/core.py::Engine.run", "caller"),
        ("code:lab:lab/core.py::go", "symbol")]                             # Engine's lines, LIMIT's: untouched
    assert [s["name"] for s in d["unmapped"]] == ["helper", "go"]          # the nested go: no CodeRef names it
    assert [q for q in gn.queries if "'CALLS'" in q and "r.confidence >= 0.8" not in q] == []


def test_the_checklist_from_the_nodes_relying_on_them(lab, make_repo, monkeypatch, capsys):
    _chain(lab, make_repo, monkeypatch)
    d = _impact(capsys, lab)[1]
    assert [(f["id"], f["status"], f["direct"]) for f in d["features"]] == [
        ("feat-all", "partial", False), ("feat-cli", "have", True), ("feat-go", "planned", True)]
    assert _ids(d["items"]) == ["wi-go"]                                    # the done item is not listed
    assert [(x["id"], x.get("supersedes")) for x in d["decisions"]] == [("adr-new", "adr-old")]
    assert (_ids(d["specs"]), _ids(d["ddrs"])) == (["spec-go"], ["ddr-go"])
    assert [(x["path"], x["why"]) for x in d["docs"]] == [("README.md", "documents feat-cli"),
                                                         ("docs/guide.md", "names src/lab/core.py")]
    assert [(t["path"], t["why"]) for t in d["tests"]] == [
        ("tests/Lab.Tests.ps1", "covers src/lab/core.py"), ("tests/test_cli.py", "covers src/lab/cli.py"),
        ("tests/test_core.py", "tests feat-go"), ("tests/test_new.py", "changed here")]
    assert d["pytest"] == "pytest tests/test_cli.py tests/test_core.py tests/test_new.py"
    assert d["wider_tests"] == ["test:lab:tests/test_misc.py"]
    assert _ids(d["workflows"]) == ["workflow:lab:.github/workflows/ci.yml::test"]


def test_the_text_view(lab, make_repo, monkeypatch, capsys):
    _chain(lab, make_repo, monkeypatch)
    cli.main(["impact", "--repo-dir", str(lab)])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("== impact demo/lab: main@")
    assert out[0].endswith("..worktree, 2 file(s) changed")
    assert out[1] == f"symbols (GitNexus, index at {_sha(lab, 'main')[:7]}): 3 touched in 1 file(s), 2 caller(s)"
    for line in ("    feat-go (planned): implemented by code:lab:lab/core.py::go; this change may make it partial or "
                 "have", "    feat-all (partial): part of a touched feature; this change may complete it (have) "
                 "(through its part)", "    pytest tests/test_cli.py tests/test_core.py tests/test_new.py",
                 "    tests/Lab.Tests.ps1 (pester)", "    CI: .github/workflows/ci.yml::test",
                 "    docs/guide.md: Core (names src/lab/core.py)", "    wi-go (todo): Ship go"):
        assert line in out
    assert out[-1].startswith("touched symbols no CodeRef names (2; the graph does not see them): src/lab/core.py::")


def test_without_gitnexus_the_file_level_says_so_and_reads_the_ast(lab, make_repo, monkeypatch, capsys):
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, CALLS, up=False)
    make_repo.write(lab, {"src/lab/core.py": GO2})
    rc, d = _impact(capsys, lab)
    assert rc == 0 and d["mode"] == "files" and d["index"] == "" and d["symbols"] == d["callers"] == []
    assert d["why_files"] == "gitnexus does not answer at http://127.0.0.1:4747: brain up gitnexus, then brain index lab"
    assert [(t["ref"], t["how"], t["via"]) for t in d["coderefs"]] == [("code:lab:lab/core.py::go", "ast", "modified")]
    assert _ids(d["features"]) == ["feat-all", "feat-go"]                  # no caller followed: feat-cli is not
    cli.main(["impact", "--repo-dir", str(lab)])
    assert capsys.readouterr().out.splitlines()[1] == (
        "FILE LEVEL (no symbol, no caller): gitnexus does not answer at http://127.0.0.1:4747: brain up gitnexus, "
        "then brain index lab")


def test_a_repo_gitnexus_has_not_indexed_is_read_at_the_file_level(lab, make_repo, monkeypatch, capsys):
    FakeGitNexus(monkeypatch, {})
    make_repo.write(lab, {"src/lab/core.py": CORE.replace("LIMIT = 3", "LIMIT = 4"), "README.md": "# Lab 2\n"})
    rc, d = _impact(capsys, lab)
    assert d["why_files"] == "lab is not indexed: brain index lab"
    assert [(t["ref"], t["how"]) for t in d["coderefs"]] == [("code:lab:README.md", "file (no index)"),
                                                             ("code:lab:lab/core.py::LIMIT", "ast")]


def test_an_index_older_than_the_base_is_noted(lab, make_repo, monkeypatch, capsys):
    indexed = _sha(lab)
    run_git(lab, "checkout", "-q", "main")
    make_repo.commit(lab, {"src/lab/core.py": CORE.replace("LIMIT = 3", "LIMIT = 4")})   # main moves on
    run_git(lab, "checkout", "-q", "-B", "feature")
    make_repo.write(lab, {"src/lab/core.py": GO2.replace("LIMIT = 3", "LIMIT = 4")})
    FakeGitNexus(monkeypatch, {"lab": (lab, indexed)})
    rc, d = _impact(capsys, lab)
    assert d["note"].startswith(f"the index is at {indexed[:7]}, the base at {_sha(lab, 'main')[:7]}")
    assert {t["ref"] for t in d["coderefs"]} == {"code:lab:lab/core.py::go", "code:lab:lab/core.py::LIMIT"}


def test_a_commit_range_with_a_rename_and_a_deletion(lab, make_repo, monkeypatch, capsys):
    FakeGitNexus(monkeypatch, {}, up=False)
    a = _sha(lab)
    cli_text = (lab / "src/lab/cli.py").read_text(encoding="utf-8")
    b = make_repo.commit(lab, {"src/lab/cli.py": None, "src/lab/cmd.py": cli_text + "\nX = 1\n", "README.md": None,
                               "src/lab/core.py": CORE.replace("def helper():", "def helper():  # one line")})
    rc, d = _impact(capsys, lab, "--diff", f"{a}..{b}")
    assert d["new"] == b and d["base"] == a
    assert sorted((f["status"], f["old"], f["new"]) for f in d["files"]) == [
        ("D", "README.md", ""), ("M", "src/lab/core.py", "src/lab/core.py"),
        ("R", "src/lab/cli.py", "src/lab/cmd.py")]
    assert [(t["ref"], t["how"], t["via"]) for t in d["coderefs"]] == [
        ("code:lab:README.md", "file (no index)", "removed with its file"),
        ("code:lab:lab/cli.py", "file (no index)", "its file moved to src/lab/cmd.py"),
        ("code:lab:lab/cli.py::main", "file (no index)", "its file moved to src/lab/cmd.py")]   # helper: no CodeRef
    assert _ids(d["features"]) == ["feat-cli"]


def test_an_edit_on_a_symbols_last_line_or_a_one_line_symbol_is_found(lab, make_repo, monkeypatch, capsys):
    """GitNexus counts lines from 0 (the fake keeps its rows), git from 1: go's last line and the constant LIMIT."""
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))})
    make_repo.write(lab, {"src/lab/core.py": GO2.replace("LIMIT = 3", "LIMIT = 4")})
    d = _impact(capsys, lab)[1]
    assert [(s["name"], s["lines"]) for s in d["symbols"]] == [("go", [1, 2]), ("LIMIT", [10, 10])]
    assert [(t["ref"], t["how"]) for t in d["coderefs"]] == [("code:lab:lab/core.py::LIMIT", "symbol"),
                                                             ("code:lab:lab/core.py::go", "symbol")]


def test_a_moved_file_leaves_its_placed_coderefs_dangling(lab, monkeypatch, capsys):
    """A pure rename has no hunk: the CodeRefs the index placed in the old path are touched all the same."""
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, CALLS)
    run_git(lab, "mv", "src/lab/core.py", "src/lab/engine.py")
    d = _impact(capsys, lab)[1]
    assert (d["mode"], d["symbols"]) == ("gitnexus", [])
    assert {t["ref"]: t["via"] for t in d["coderefs"]} == {
        f"code:lab:lab/core.py::{s}": "its file moved to src/lab/engine.py"
        for s in ("go", "Engine", "Engine.run", "LIMIT", "gone")}
    assert _ids(d["features"]) == ["feat-all", "feat-engine", "feat-go"]


def test_a_deleted_or_moved_test_module_never_reaches_the_pytest_line(lab, make_repo, monkeypatch, capsys):
    FakeGitNexus(monkeypatch, {}, up=False)
    run_git(lab, "checkout", "-q", "main")
    make_repo.commit(lab, {"tests/test_core.py": "def test_a():\n    pass\n", "tests/test_gone.py": "def test_b():\n"
                           "    pass\n", "docs/guide.md": "# Guide\n\n## Core\n"})
    run_git(lab, "checkout", "-q", "-B", "feature")
    run_git(lab, "mv", "tests/test_core.py", "tests/test_core2.py")
    run_git(lab, "rm", "-q", "tests/test_gone.py", "docs/guide.md")
    d = _impact(capsys, lab)[1]
    assert d["pytest"] == "pytest tests/test_core2.py"                   # not the paths that are gone
    assert [(x["path"], x["why"]) for x in d["docs"]] == [("docs/guide.md", "removed by this change")]


def test_a_failed_code_map_falls_back_to_the_file_level(lab, make_repo, monkeypatch, capsys):
    """The census of the map times out while the other queries answer: the run says so, never a silent half."""
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, CALLS, fail="MATCH (f:File)")
    make_repo.write(lab, {"src/lab/core.py": GO2})
    rc, d = _impact(capsys, lab)
    assert (rc, d["mode"], d["symbols"], d["callers"]) == (0, "files", [], [])
    assert d["why_files"] == "the code map of lab: GitNexus: timed out"
    assert [(t["ref"], t["how"], t["via"]) for t in d["coderefs"]] == [("code:lab:lab/core.py::go", "ast", "modified")]


@pytest.mark.parametrize("up", [False, True])
def test_a_malformed_coderef_is_left_out_not_a_crash(lab, make_repo, monkeypatch, capsys, up):
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, up=up)
    make_repo.write(lab, {"src/lab/core.py": GO2, "notes/graph/nodes/extra.yaml":
                          '- {id: "code:lab:tools/x.ps1::Foo", type: CodeRef, status: active, title: x}\n'})
    rc, d = _impact(capsys, lab)
    assert (rc, d["malformed"]) == (0, ["code:lab:tools/x.ps1::Foo"])
    assert [t["ref"] for t in d["coderefs"]] == ["code:lab:lab/core.py::go"]
    cli.main(["impact", "--repo-dir", str(lab)])
    assert "malformed CodeRef(s) left out (1): code:lab:tools/x.ps1::Foo" in capsys.readouterr().out.splitlines()


def test_hunk_bodies_are_never_read_as_headers_whatever_the_git_config(lab, make_repo, monkeypatch):
    """In a -U0 diff a deleted line '-- x' reads '--- x' and an added '++ y' reads '+++ y'; diff.noprefix and
    diff.mnemonicPrefix change the a/ and b/ prefixes; a filter on paths never goes to git's command line."""
    base = make_repo.commit(lab, {"src/lab/q.sql": "select 1;\n-- the comment\n", "src/lab/old.sql": "-- bye\n"})
    make_repo.write(lab, {"src/lab/q.sql": "select 1;\n++ added\n", "src/lab/old.sql": None})
    for i, (k, v) in enumerate((("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"))):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{i}", k)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{i}", v)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    h = impact.hunks(lab, base)
    assert sorted((c.status, c.old, c.new, c.old_lines, c.new_lines) for c in h.values()) == [
        ("D", "src/lab/old.sql", "", [(1, 1)], []),
        ("M", "src/lab/q.sql", "src/lab/q.sql", [(2, 2)], [(2, 2)])]
    assert list(impact.hunks(lab, base, files=["src/lab/old.sql"])) == ["src/lab/old.sql"]


def test_hunks_cover_both_sides_and_an_insertion_touches_the_line_it_follows(lab, make_repo):
    base = _sha(lab)
    make_repo.write(lab, {"src/lab/core.py": CORE.replace("LIMIT = 3\n", "LIMIT = 3\nMORE = 1\n")
                          .replace("def go():\n    return 1\n", "")})
    h = impact.hunks(lab, base)
    c = h["src/lab/core.py"]
    assert (c.status, c.old, c.new) == ("M", "src/lab/core.py", "src/lab/core.py")
    assert c.old_lines == [(1, 2), (10, 10)] and c.new_lines == [(9, 9)]   # go's two lines gone, a line added
    assert diffs._span(0, 0) is None and diffs._span(5, 0) == (5, 5) and diffs._span(5, 2) == (5, 6)


def test_a_change_outside_any_coderef_lists_only_the_docs_it_edits(lab, make_repo, monkeypatch, capsys):
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, CALLS)
    make_repo.write(lab, {"docs/notes.txt": "x\n", "docs/guide.md": "# Guide\n\n## Core\n"})
    rc, d = _impact(capsys, lab)
    assert rc == 0 and d["coderefs"] == d["features"] == d["tests"] == [] and d["pytest"] == ""
    assert [(x["path"], x["why"]) for x in d["docs"]] == [("docs/guide.md", "changed here")]
    cli.main(["impact", "--repo-dir", str(lab)])
    assert "    docs/guide.md: edited by this change" in capsys.readouterr().out.splitlines()
    run_git(lab, "checkout", "-q", "--", ".")
    run_git(lab, "clean", "-qfd")
    cli.main(["impact", "--repo-dir", str(lab)])
    assert capsys.readouterr().out.splitlines()[1] == "no file changed"


def test_no_base_exits_2(lab, capsys):
    assert cli.main(["impact", "--diff", "nowhere", "--repo-dir", str(lab)]) == 2
    assert capsys.readouterr().err.startswith("brain impact: ")
