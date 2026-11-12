"""brain test --changed (wi-brain-targeted-tests): the test modules a change touches, by the coverage map; missing,
stale or incomplete evidence widens to the whole suite, a static import only adds a test, never drops one."""

import json

from brain import cli, targeted

CORE = "LIMIT = 3\n\n\ndef limit():\n    return LIMIT\n"
USE = "from p import core\n\nDOUBLE = core.LIMIT * 2\n\n\ndef double():\n    return DOUBLE\n"
OTHER = '"""Other."""\n\n\ndef other():\n    return 1\n'
FILES = {
    "pyproject.toml": "[project]\nname = \"p\"\n\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
    "src/p/__init__.py": "",
    "src/p/core.py": CORE,
    "src/p/use.py": USE,
    "src/p/other.py": OTHER,
    "tests/test_core.py": "from p import core\n\n\ndef test_limit():\n    assert core.limit() == 3\n",
    "tests/test_use.py": "from p import use\n\n\ndef test_double():\n    assert use.double() == 6\n",
    "tests/test_other.py": "from p.other import other\n\n\ndef test_other():\n    assert other() == 1\n",
    "tests/test_docs.py": "def test_docs():\n    assert open('docs/guide.md').read()\n",
    "docs/guide.md": "# Guide\n",
}


def _map(commit, dirty=False):
    return {"version": 2, "repo": "lab", "commit": commit, "dirty": dirty, "test_modules": [
        "tests/test_core.py", "tests/test_docs.py", "tests/test_other.py", "tests/test_use.py"],
        "files": {"src/p/core.py": {"functions": ["limit"], "tests": {"tests/test_core.py": ["limit"]}},
                  "src/p/use.py": {"functions": ["double"], "tests": {"tests/test_use.py": ["double"]}},
                  "src/p/other.py": {"functions": ["other"], "tests": {"tests/test_other.py": ["other"]}},
                  "src/p/__init__.py": {"functions": []}}}


def _select(repo, summary, inert=None):
    base, rev = "main", targeted.git(repo, "rev-parse", "main").strip()
    return targeted.select(repo, "lab", base, rev, summary, None, inert)


def _head(repo):
    return targeted.git(repo, "rev-parse", "HEAD").strip()


def test_a_function_body_change_selects_the_tests_that_ran_it(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    sel = _select(repo, summary)
    assert sel.complete, sel.widen
    assert sel.tests == {"tests/test_other.py": "ran src/p/other.py"}


def test_a_change_selects_its_importers_tests_too(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    # use.py calls into core at import (DOUBLE = core.LIMIT * 2): that line runs in no test's context, so a change
    # to core, at its module level or in a body, runs the tests of what imports it
    for edit in (CORE.replace("LIMIT = 3", "LIMIT = 4"), CORE.replace("return LIMIT", "return LIMIT + 0")):
        make_repo.write(repo, {"src/p/core.py": edit})
        sel = _select(repo, summary)
        assert sel.complete, sel.widen
        assert set(sel.tests) == {"tests/test_core.py", "tests/test_use.py"}
        assert sel.tests["tests/test_use.py"] == "ran src/p/use.py (imports a changed module)"


def test_a_conftest_that_imports_a_changed_module_selects_its_folder(make_repo):
    repo = make_repo("lab", {**FILES, "tests/conftest.py": "from p import other\n"})
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    sel = _select(repo, summary)
    assert set(sel.tests) == set(sel.suite)


def test_a_deleted_module_widens_and_runs_what_imported_it(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/core.py": None, "tests/test_core.py": None})
    sel = _select(repo, summary)
    assert not sel.complete and "src/p/core.py: deleted" in sel.widen[0]
    assert sel.tests == {}   # use.py imports core, but no test module imports p.core any more: the widening says it
    make_repo.write(repo, {"tests/test_left.py": "from p import core\n"})
    assert "tests/test_left.py" in _select(repo, summary).tests


def test_a_test_file_pytest_does_not_collect_widens(make_repo):
    repo = make_repo("lab", {**FILES, "tests/bin/fake.sh": "echo 1\n",
                             "tests/test_fake.py": "def test_f():\n    assert 'bin/fake.sh'\n"})
    summary = _map(_head(repo))
    make_repo.write(repo, {"tests/bin/fake.sh": "echo 2\n"})
    sel = _select(repo, summary)
    assert not sel.complete and sel.tests == {"tests/test_fake.py": "names fake.sh"}


def test_a_test_that_starts_python_runs_with_any_python_change(make_repo):
    spawn = "import subprocess, sys\n\n\ndef test_cli():\n    subprocess.run([sys.executable, '-m', 'p'])\n"
    repo = make_repo("lab", {**FILES, "tests/test_cli.py": spawn})
    summary = _map(_head(repo))
    summary["test_modules"].append("tests/test_cli.py")
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    assert _select(repo, summary).tests["tests/test_cli.py"] == "starts a Python process"
    make_repo.write(repo, {"src/p/other.py": OTHER, "tests/test_docs.py": FILES["tests/test_docs.py"] + "\n"})
    assert "tests/test_cli.py" not in _select(repo, summary).tests   # no Python module changed


def test_a_changed_test_runs_itself_only(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"tests/test_use.py": FILES["tests/test_use.py"] + "\n\ndef test_more():\n    pass\n"})
    sel = _select(repo, summary)
    assert sel.complete and sel.tests == {"tests/test_use.py": "changed here"}


def test_a_conftest_selects_every_test_under_its_folder(make_repo):
    repo = make_repo("lab", FILES)
    make_repo.write(repo, {"tests/conftest.py": "import pytest\n"})
    sel = _select(repo, _map(_head(repo)))
    assert set(sel.tests) == set(sel.suite) and len(sel.suite) == 4


def test_a_file_coverage_cannot_see_widens_and_adds_the_tests_naming_it(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"docs/guide.md": "# Guide, edited\n"})
    sel = _select(repo, summary)
    assert not sel.complete and "docs/guide.md" in sel.widen[0]
    assert sel.tests == {"tests/test_docs.py": "names guide.md"}
    # declared inert: no test reads it, the answer is complete
    sel = _select(repo, summary, inert=["docs/*.md"])
    assert sel.complete and sel.inert == ["docs/guide.md"] and not sel.tests


def test_a_name_counts_whole_and_an_installer_script_is_no_test_module(make_repo):
    repo = make_repo("lab", {**FILES, "installer/stranger_test.py": "print('a script')\n",
                             "tests/test_stranger.py": "def test_s():\n    assert 'stranger_guide.md'\n"})
    summary = _map(_head(repo))
    make_repo.write(repo, {"docs/guide.md": "# Guide, edited\n"})
    sel = _select(repo, summary)
    assert "installer/stranger_test.py" not in sel.suite and "tests/test_stranger.py" in sel.suite
    assert set(sel.tests) == {"tests/test_docs.py"}   # stranger_guide.md does not name guide.md


def test_a_module_the_map_never_measured_widens(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/new.py": "def new():\n    return 0\n"})
    sel = _select(repo, summary)
    assert any("src/p/new.py: never measured" in w for w in sel.widen)


def test_no_map_a_dirty_map_or_a_foreign_commit_widens(make_repo):
    repo = make_repo("lab", FILES)
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    assert "no coverage map" in _select(repo, None).widen[0]
    assert "dirty" in _select(repo, _map(_head(repo), dirty=True)).widen[0]
    sel = _select(repo, _map("0123456789abcdef0123456789abcdef01234567"))
    assert "unknown here" in sel.widen[0]
    assert sel.tests == {"tests/test_other.py": "ran src/p/other.py"}   # still run first


def test_what_changed_since_the_map_is_run_again(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.commit(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})   # merged on main since
    sel = _select(repo, summary)   # the base is HEAD: nothing changed since it, but since the map
    assert sel.tests == {"tests/test_other.py": "ran src/p/other.py"}


def test_a_test_module_missing_from_the_map_runs_with_any_python_change(make_repo):
    repo = make_repo("lab", {**FILES, "tests/test_proc.py": "def test_proc():\n    pass\n"})
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    sel = _select(repo, summary)
    assert sel.tests["tests/test_proc.py"] == "not in the map"


def test_the_commands_group_test_modules_by_their_pytest_configuration(tmp_path):
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "pkg" / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    cmds = targeted.commands(tmp_path, ["pkg/tests/test_a.py", "tests/test_b.py"], python="py", workers="2")
    assert cmds == [(tmp_path, ["py", "-m", "pytest", "tests/test_b.py", "-n", "2"]),
                    (tmp_path / "pkg", ["py", "-m", "pytest", "tests/test_a.py", "-n", "2"])]


def test_brain_test_changed_lists_runs_and_records(make_repo, tmp_path, capsys, monkeypatch):
    repo = make_repo("lab", FILES)
    m = tmp_path / "map.json"
    m.write_text(json.dumps(_map(_head(repo))), encoding="utf-8")
    make_repo.write(repo, {"src/p/other.py": OTHER.replace("return 1", "return 2")})
    assert cli.main(["test", "--changed", "--repo-dir", str(repo), "--map", str(m), "--list", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] and [t["path"] for t in out["tests"]] == ["tests/test_other.py"]
    ran = []
    monkeypatch.setattr(targeted, "run", lambda top, tests, *a, **k: ran.append(tests) or 0)
    assert cli.main(["test", "--changed", "--repo-dir", str(repo), "--map", str(m)]) == 0
    assert ran == [["tests/test_other.py"]]
    # shadow mode: a widened answer runs the selection only, and says so; --strict runs the whole suite
    make_repo.write(repo, {"docs/guide.md": "# Guide, edited\n"})
    assert cli.main(["test", "--changed", "--repo-dir", str(repo), "--map", str(m)]) == 0
    assert "shadow mode" in capsys.readouterr().err
    assert ran[-1] == ["tests/test_docs.py", "tests/test_other.py"]
    assert cli.main(["test", "--changed", "--repo-dir", str(repo), "--map", str(m), "--strict"]) == 0
    assert len(ran[-1]) == 4
    led = [json.loads(x) for x in (targeted.paths.ledger_dir() / targeted.LEDGER).read_text(
        encoding="utf-8").splitlines()]
    assert [x["mode"] for x in led] == ["shadow", "shadow", "strict"]
    assert led[1]["complete"] is False and led[2]["ran"] == 4
