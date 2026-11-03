import json

import pytest

from brain import cli, scout

from conftest import run_git
from test_audit import FIND, GUARD, README

SCHEMA = ("node_types: [WorkItem, Milestone, Spec, CodeRef, Repo]\nedge_types: [specified_by, depends_on, part_of]\n"
          "statuses: [active, todo, doing, done, dropped, pending, reached]\n"
          "status_by_type:\n  WorkItem: [todo, doing, done, dropped]\n")
LAB = {"README.md": README, "pyproject.toml": '[project.scripts]\nlab = "lab.cli:main"\n' + FIND,
       "src/lab/__init__.py": "", "src/lab/cli.py": "from lab import core\n\ndef main():\n    core.go()\n",
       "src/lab/core.py": "def go():\n    pass\n",
       "src/lab/old.py": '"""Old."""\nimport os\n\n\ndef f():\n    pass\n',
       "tests/test_cli.py": "from lab.cli import main\n", "tests/test_core.py": "from lab.core import go\n",
       "docs/guide.md": "The core: src/lab/core.py.\n",
       "notes/graph/schema.yaml": SCHEMA, "notes/graph/edges/work.yaml": "# edges\n",
       "notes/graph/nodes/code.yaml": "- {id: repo-lab, type: Repo, status: active, title: lab}\n"
                                      + "".join(f'- {{id: "code:lab:lab/{m}.py", type: CodeRef, status: active, '
                                                f'title: {m}}}\n' for m in ("cli", "core", "old"))}
MORE = "\n\ndef g():\n    return 1\n"


def _setup(make_repo, tmp_path, monkeypatch, files=None, extra=""):
    lab = make_repo("lab", files or LAB)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {lab.as_posix()}, production: [.]{extra}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(lab, "checkout", "-q", "-b", "feature")
    return lab


def _scout(capsys, repo, *args):
    rc = cli.main(["audit", "--diff", *args, "--repo-dir", str(repo), "--json"])
    data = json.loads(capsys.readouterr().out)
    return rc, {(f["check"], f["unit"]): f["tag"] for f in data["findings"]}, data


def _append(repo, rel, text):
    f = repo / rel
    f.write_text(f.read_text(encoding="utf-8") + text, encoding="utf-8", newline="\n")


def test_new_left_and_an_untracked_file(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _append(lab, "src/lab/old.py", MORE)
    (lab / "src" / "lab" / "new.py").write_text("def h():\n    pass\n", encoding="utf-8")
    rc, tags, data = _scout(capsys, lab)
    assert rc == 1 and data["project"] == "demo" and data["repo"] == "lab"
    assert tags == {("test.module", "src/lab/old.py"): "LEFT", ("test.module", "src/lab/new.py"): "NEW",
                    ("coderef.module", "src/lab/new.py"): "NEW"}
    assert cli.main(["audit", "--diff", "--repo-dir", str(lab)]) == 1
    out = capsys.readouterr().out
    assert "LEFT   P2 test.module      src/lab/old.py other:" in out
    assert out.rstrip().endswith("scout: 3 to fix in this PR (2 NEW, 1 LEFT), 0 deferred; then brain audit --diff "
                                 "again")


def test_light_touches_and_a_pure_rename_never_make_left_block(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, "scripts/run.ps1": "echo run\n"})
    (lab / "src" / "lab" / "old.py").write_text('"""Old, said again."""\nimport os\nimport sys\n\ndef f( ):\n'
                                                '    pass\n', encoding="utf-8")
    (lab / "scripts" / "run.ps1").write_text("echo   run\n\n", encoding="utf-8")
    rc, tags, _ = _scout(capsys, lab)
    assert rc == 0 and tags[("test.module", "src/lab/old.py")] == "light"
    assert tags[("test.script", "scripts/run.ps1")] == "info"     # no harness for .ps1 here: advisory
    run_git(lab, "checkout", "-q", "--", ".")
    run_git(lab, "mv", "src/lab/old.py", "src/lab/older.py")
    assert scout.changed(lab, run_git(lab, "rev-parse", "main").strip()) == [
        ("R100", "src/lab/old.py", "src/lab/older.py")]
    rc, tags, _ = _scout(capsys, lab)
    assert tags[("test.module", "src/lab/older.py")] == "light"
    assert rc == 1 and tags[("coderef.dangling", "code:lab:lab/old.py")] == "NEW"   # the old path still checked


def test_a_deleted_module_still_named_by_a_coderef_or_a_doc_is_p0_new(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    run_git(lab, "rm", "-q", "src/lab/core.py")
    rc, tags, data = _scout(capsys, lab)
    assert rc == 1
    assert tags[("coderef.dangling", "code:lab:lab/core.py")] == "NEW"
    assert tags[("doc.dead-ref", "docs/guide.md#src/lab/core.py")] == "NEW"
    assert {f["severity"] for f in data["findings"] if f["tag"] == "NEW"} == {"P0"}


def test_the_limit_defers_left_units_production_first(make_repo, tmp_path, monkeypatch, capsys):
    mods = {f"src/lab/{m}.py": "def f():\n    pass\n" for m in ("e1", "e2", "p1", "o1", "o2")}
    mods["src/lab/e1.py"] = "from lab import p1\n\ndef f():\n    pass\n"
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, **mods, "src/lab/cli.py": "from lab import core, e1, e2\n"
                                                    "\ndef main():\n    core.go()\n"})
    for rel in mods:
        _append(lab, rel, MORE)
    rc, tags, data = _scout(capsys, lab, "--limit", "2")
    got = {u.split("/")[-1]: t for (c, u), t in tags.items() if c == "test.module"}
    assert rc == 1 and got == {"e1.py": "LEFT", "e2.py": "LEFT", "p1.py": "DEFER", "o1.py": "DEFER",
                               "o2.py": "DEFER"}
    assert data["deferred"] == 3 and data["item"] == "wi-debt-lab"
    cli.main(["audit", "--diff", "--limit", "2", "--repo-dir", str(lab)])
    assert "brain --project demo item add wi-debt-lab" in capsys.readouterr().out


def test_a_script_left_blocks_only_where_a_test_already_runs_such_scripts(make_repo, tmp_path, monkeypatch, capsys):
    files = {**LAB, "scripts/run.ps1": "echo run\n", "scripts/named.ps1": "echo\n",
             "tests/test_named.py": "def test(): pass\n"}
    lab = _setup(make_repo, tmp_path, monkeypatch, files)
    (lab / "scripts" / "run.ps1").write_text("echo run twice\n", encoding="utf-8")
    rc, tags, _ = _scout(capsys, lab)
    assert rc == 1 and tags[("test.script", "scripts/run.ps1")] == "LEFT"


def test_a_sibling_repo_worktree_resolves_its_project(make_repo, tmp_path, monkeypatch, capsys):
    md = make_repo("md", {"README.md": README, "pyproject.toml": FIND, "src/md/__init__.py": "",
                          "src/md/store.py": "def save():\n    pass\n", "tests/test_store.py": "x\n"})
    _setup(make_repo, tmp_path, monkeypatch, extra=", repos: [., ../md]")
    wt = tmp_path / "wt" / "md"
    run_git(md, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "src" / "md" / "fresh.py").write_text("def f():\n    pass\n", encoding="utf-8")
    rc, tags, data = _scout(capsys, wt)
    assert (data["project"], data["repo"]) == ("demo", "md")
    assert rc == 1 and tags == {("test.module", "src/md/fresh.py"): "NEW"}


def test_a_commit_range_replays_commits_only_and_no_base_exits_2(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    a = run_git(lab, "rev-parse", "HEAD").strip()
    b = make_repo.commit(lab, {"src/lab/new.py": "def h():\n    pass\n"}, date="2026-10-02T12:00:00Z")
    (lab / "src" / "lab" / "stray.py").write_text("def s():\n    pass\n", encoding="utf-8")   # not committed
    rc, tags, data = _scout(capsys, lab, f"{a}..{b}")
    assert rc == 1 and set(tags) == {("test.module", "src/lab/new.py"), ("coderef.module", "src/lab/new.py")}
    assert data["base"] == a and data["new"] == b
    assert cli.main(["audit", "--diff", "nosuch", "--repo-dir", str(lab)]) == 2
    assert "nosuch" in capsys.readouterr().err


def test_an_unregistered_repo_is_audited_with_the_defaults(make_repo, tmp_path, monkeypatch, capsys):
    lone = make_repo("lone", {"README.md": README, "pyproject.toml": FIND, "src/lone/__init__.py": "",
                              "src/lone/m.py": "def f():\n    pass\n", "tests/test_m.py": "x\n"})
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "empty.yaml"))
    run_git(lone, "checkout", "-q", "-b", "feature")
    (lone / "src" / "lone" / "n.py").write_text("def g():\n    pass\n", encoding="utf-8")
    assert cli.main(["audit", "--diff", "--repo-dir", str(lone)]) == 1
    out = capsys.readouterr()
    assert "in no registered project" in out.err and "N/A    coderef.dangling" in out.out


LAB2 = {**LAB, "README.md": README + "Run `python -m lab.tool`, or `python -m lab`.\n",
        "src/lab/tool.py": GUARD, "src/lab/__main__.py": "from lab.cli import main\nmain()\n",
        "tests/test_tool.py": "from lab.tool import run\n",
        "docs/x/b.md": "Next to this doc: scripts/local.ps1.\n", "docs/x/scripts/local.ps1": "x\n",
        "scripts/run.ps1": "echo run\n", "tools/sweep.py": "print(1)\n", "docs/tools.md": "The sweep: tools/sweep.py.\n",
        "hooks/run.py": "import sys\nfrom lab.core import go\nsys.exit(go())\n"}


def _new(capsys, lab):
    rc, tags, _ = _scout(capsys, lab)
    run_git(lab, "reset", "-q", "--hard")
    run_git(lab, "clean", "-fdq")
    return rc, {k for k, t in tags.items() if t == "NEW"}


def test_new_is_any_finding_the_base_did_not_have(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch, LAB2)
    assert _scout(capsys, lab)[0] == 0
    run_git(lab, "rm", "-q", "docs/x/scripts/local.ps1")          # a path a doc names next to itself
    assert _new(capsys, lab) == (1, {("doc.dead-ref", "docs/x/b.md#scripts/local.ps1")})
    run_git(lab, "mv", "src/lab/tool.py", "src/lab/tools.py")     # a module the README runs with -m
    rc, new = _new(capsys, lab)
    assert rc == 1 and ("doc.dead-ref", "README.md#-m lab.tool") in new
    run_git(lab, "rm", "-q", "src/lab/__main__.py")               # python -m lab no longer runs
    assert ("doc.dead-ref", "README.md#-m lab") in _new(capsys, lab)[1]
    run_git(lab, "rm", "-q", "README.md")
    assert ("readme.exists", "README.md") in _new(capsys, lab)[1]
    (lab / "pyproject.toml").write_text(LAB["pyproject.toml"].replace("[project.scripts]\n", "[project.scripts]\n"
                                        'lab-secret = "lab.cli:main"\n'), encoding="utf-8")   # a console script
    assert _new(capsys, lab) == (1, {("cmd.documented", "lab-secret")})
    _append(lab, "notes/graph/nodes/code.yaml", '- {id: "code:lab:lab/cor.py", type: CodeRef, status: active, '
                                                'title: a typo}\n')
    assert _new(capsys, lab) == (1, {("coderef.dangling", "code:lab:lab/cor.py")})
    run_git(lab, "rm", "-q", "tools/sweep.py")                    # the last file of a top-level folder
    assert _new(capsys, lab) == (1, {("doc.dead-ref", "docs/tools.md#tools/sweep.py")})
    run_git(lab, "rm", "-q", "tests/test_core.py")                # a deleted test: the module and its shim
    assert _new(capsys, lab) == (1, {("test.module", "src/lab/core.py"), ("test.script", "hooks/run.py")})


def test_a_test_edit_touches_no_module_and_left_ranks_by_severity(make_repo, tmp_path, monkeypatch, capsys):
    files = {**LAB, "src/lab/job.py": GUARD, "tests/test_job.py": "from lab.job import run\n",
             "docs/guide2.md": "Gone: src/lab/gone1.py and src/lab/gone2.py.\n",
             **{f"src/lab/{m}.py": "def f():\n    pass\n" for m in ("a", "b", "c")}}
    lab = _setup(make_repo, tmp_path, monkeypatch, files)
    _append(lab, "tests/test_job.py", "\n\ndef test_more():\n    assert True\n")   # lab.job is undocumented
    rc, tags, _ = _scout(capsys, lab)
    assert rc == 0 and tags == {}
    run_git(lab, "checkout", "-q", "--", ".")
    _append(lab, "docs/guide2.md", "More.\n")
    for m in ("a", "b", "c"):
        _append(lab, f"src/lab/{m}.py", MORE)
    rc, tags, _ = _scout(capsys, lab)
    assert tags[("doc.dead-ref", "docs/guide2.md#src/lab/gone1.py")] == "LEFT"   # P0 first; one doc, one unit
    assert tags[("doc.dead-ref", "docs/guide2.md#src/lab/gone2.py")] == "LEFT"
    assert sorted(t for (c, u), t in tags.items() if c == "test.module") == ["DEFER", "LEFT", "LEFT"]
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", "--diff", "--limit", "-1", "--repo-dir", str(lab)])
    assert exc.value.code == 2 and "0 or more" in capsys.readouterr().err


def test_the_default_base_is_the_newer_of_main_and_origin_main(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    merged = make_repo.commit(lab, {"src/lab/merged.py": "def m():\n    pass\n"}, date="2026-10-02T12:00:00Z")
    run_git(lab, "update-ref", "refs/remotes/origin/main", merged)   # merged on origin, local main not pulled
    run_git(lab, "checkout", "-q", "-b", "pr2")
    _append(lab, "src/lab/core.py", "# a comment\n")
    rc, tags, data = _scout(capsys, lab)
    assert data["base_ref"] == "origin/main" and data["base"] == merged
    assert rc == 0 and ("test.module", "src/lab/merged.py") not in tags
    rc, tags, data = _scout(capsys, lab, "main")                   # a base named: as asked
    assert data["base_ref"] == "main" and tags[("test.module", "src/lab/merged.py")] == "NEW"
