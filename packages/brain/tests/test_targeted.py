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


def test_a_module_level_change_selects_its_importers_tests_too(make_repo):
    repo = make_repo("lab", FILES)
    summary = _map(_head(repo))
    make_repo.write(repo, {"src/p/core.py": CORE.replace("LIMIT = 3", "LIMIT = 4")})
    sel = _select(repo, summary)
    assert sel.complete, sel.widen
    # use.py reads core.LIMIT at import: a test that runs only use.double is touched by core's module level
    assert set(sel.tests) == {"tests/test_core.py", "tests/test_use.py"}
    assert "imports a changed module level" in sel.tests["tests/test_use.py"]


def test_a_docstring_or_body_only_change_is_not_a_module_level_one():
    assert targeted.skeleton(OTHER) == targeted.skeleton(OTHER.replace('"""Other."""', '"""Else."""')
                                                          .replace("return 1", "return 2"))
    assert targeted.skeleton(CORE) != targeted.skeleton(CORE.replace("LIMIT = 3", "LIMIT = 4"))
    assert targeted.skeleton("def f(a=1):\n    pass\n") != targeted.skeleton("def f(a=2):\n    pass\n")


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
    assert "not in HEAD's history" in sel.widen[0]
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
